# Issues Faced During the Build

A record of the problem types encountered while building the agentic RAG
system, drawn from the git history and from the code as it now stands
(`backend/app/...`). Useful as institutional memory: these were the hard-won
lessons, not hypotheticals.

---

## 1. RAG foundation issues

- **Duplicate chunks on re-ingestion** — every `ingest.py` run multiplied the
  chunk count. Fixed with deterministic chunk IDs derived from
  `(source, page, chunk index)` so ingestion is idempotent
  (commit `d787b50`).
- **Hallucinated answers** — the model guessed when context was insufficient.
  Fixed in two layers: a tightened RAG prompt with explicit no-guessing rules
  (`0dbf331`), and a graph-level groundedness gate —
  `backend/app/groundedness.py` judges each RAG answer against the exact
  blocks the model was shown, and `validate_node` replaces an unsupported
  answer with "I don't know based on the provided documents." and drops its
  sources. The judge deliberately fails open: an unreachable or unparsable
  verdict leaves the answer standing, because a wrong refusal discards an
  answer that may be fine. `00dfc07` had already covered the citation half —
  an unknown answer or an explicit "Sources: None" reports no sources.
- **Retrieval quality** — needed a score threshold plus a relative-score
  margin in the retriever, and golden eval sets to lock the behaviour in
  (`18f3a6b`).
- **Sources leaking host paths and over-citing** — `loader.py` stamps the
  full path, so the same file cited as `knowledge_base\hospital_info.pdf` on
  Windows and `knowledge_base/hospital_info.pdf` on Linux, and a missing
  "Sources:" line fell back to citing every retrieved chunk. `format_sources()`
  now emits the bare filename for both separators, and the trailing
  `Sources: <numbers>` line is parsed explicitly: `Sources: None` means none
  (`1daa609`).

## 2. Prompt injection / security issues

- **Retrieved documents are untrusted** — a knowledge-base chunk saying
  "ignore previous instructions" could hijack the answer. Fixed with
  `sanitize_context()` on retrieved chunks (`8f1ee50`).
- **Replayed conversation history is untrusted too** — an injected line in an
  old message survives into the prompt; it is sanitized on the way back in
  (`core.format_history()`, deliberately *not* with `check_user_input()`,
  which would abort every later turn of a conversation whose first turn once
  tripped a pattern).
- **User-input guardrails** — malicious prompts are rejected at the first
  trust boundary, before the router sees them; a blocked turn skips
  rewriting and routing entirely.
- **The groundedness judge is a second untrusted surface** — its prompt tells
  it the context and answer are data, never instructions, and it only ever
  returns one word to parse.

## 3. Identity / authorization issues

- **Anonymous access escalation** — the booking tools treated a missing user
  as the seeded demo patient, so an anonymous caller could read, book,
  reschedule or cancel that patient's appointments. Anonymous is now denied
  outright, never waved through (`19df5e2`): `_appointment_user()` returns
  "anonymous" or "role" denials before any tool runs, in both the booking
  and database nodes.
- **Cross-user data leaks** — conversation lookup filtered on id only;
  another user's `conversation_id` resolved to their thread. Now id **and**
  owner are filtered together, returning 404 (not 403) so the response does
  not confirm the row exists (`01ae0e5`).
- **Silent auth downgrade** — a malformed or expired JWT fell back to
  anonymous instead of failing. It is now a 401 (`4be7593`); only a *missing*
  header is anonymous.
- **RBAC in the wrong place** — role checks must run in Python graph nodes
  and route dependencies, never in the LLM and never from the request body.
- **Unlinked accounts falling back to demo data** — a signed-in patient or
  doctor with no linked `Patient`/`Doctor` row could have been served the
  seeded demo records; both REST helpers now fail closed with 404.

## 4. Conversation / state issues

- **Booking state in an in-process global** — `_pending` dicts broke as soon
  as two conversations interleaved. All state moved to the Neon
  `PendingBooking` table, keyed by a unique `conversation_id`; without an id
  there is no multi-turn booking state at all (`01ae0e5`).
- **Unresolvable follow-ups** — "what her fee" is unclassifiable on its own.
  Fixed twice over: follow-up query rewriting (`57cbb0f`) plus
  doctor-referent resolution from history (`4be7593`), and then
  **rewrite-before-routing** — the graph now rewrites the turn into
  `search_query` *before* the router classifies it, because the router could
  not recognise the raw follow-up either. A pending booking's bare "yes"/
  "no" bypasses the LLM router entirely so it cannot be re-routed.
- **An arbitrary referent** — a history turn listing several doctors used to
  decide "what her fee" by picking one. `referenced_doctor()` accepts only a
  turn naming **exactly one** doctor, scans user messages backwards (an
  assistant reply lists every doctor and would match arbitrarily), and a
  directory turn resolves to no referent so the full listing stays the
  answer.
- **Date parsing failures** — "28th Sept 2026", "September 28, 2026",
  weekday names, and impossible dates like "31 February" (which now yields
  `None` and asks again rather than booking the wrong day) (`01ae0e5`).
  Bare numbers were also read as times, so "appointment 3" became 03:00 —
  times now require `am`/`pm`, `hh:mm`, or an "at"-introduced hour.
- **A misspelled cancel booked instead** — "cancle my appointment" matched
  no cancel word and fell through to the booking workflow, creating the very
  appointment the user was trying to cancel. `matches_action_word()` now
  accepts a one-edit typo ("cancle", "reshedule") **only when the sentence
  is already about appointments**, so "cancer" can never trigger an action
  (`tests/test_cancel_intent.py`).
- **Appointment ids colliding with dates** — a bare number was read as an
  id, so "cancel on 19th oct" or the ordinal "3rd" could target appointment
  19/3. The id regex is now anchored (`#3`, "appointment 3", "cancel 3") and
  rejects an ordinal suffix; with no id the candidates are narrowed by the
  doctor and date the message does mention, and ambiguity asks for the
  number with a listing instead of guessing.
- **"No" was a dead end** — when the requested slot was taken the user was
  told no and nothing else. `check_slot()` now subtracts booked appointments
  from the day's windows and lists the free slots ("Free slots that day:
  11:00-12:00").
- **Past dates were bookable — still are.** `check_slot()` validates the
  weekly window and existing appointments but never the calendar, so a
  request for a past Monday (or a reschedule into last week) is accepted
  whenever the weekday matches the schedule. The appointment-API fixture
  hard-codes `MONDAY = 2026-09-28`, now in the past, and the suite stays
  green precisely because nothing rejects it. Known; **not fixed** — see the
  open edges below.

## 5. Integration / configuration issues

- **DATABASE_URL checked at import time** — importing the app without a
  configured database crashed tests and startup. The check was deferred to
  first engine use (`b1b6cad`).
- **CORS wildcard with credentials** — browsers reject `"*"` combined with
  `allow_credentials=True`. Replaced with an explicit `ALLOWED_ORIGINS`
  allow-list (`4be7593`).
- **The local Qdrant store split across cwds** — ingest ran from the repo
  root while the API server started from `backend/`, and a relative
  `qdrant_data` silently opened a second, empty collection: retrieval
  returned nothing and answers came back "I don't know" with no sources.
  `QDRANT_PATH` is now anchored to the repo root (`1daa609`).
- **Package layout** — the `app` package moved into `backend/` while
  `knowledge_base/` stays at the repo root (`1daa609`). Tests resolve the
  import through `pythonpath = ["backend", "."]` in `pyproject.toml`;
  everything else needs `backend` on `PYTHONPATH` (see plan.md's setup
  step). `main.py` and `python -m app.*` fail bare with
  `ModuleNotFoundError: No module named 'app'` until then. There is **no
  Dockerfile in this tree** to encode the setting.
- **The test suite rate-limited itself** — every `TestClient` request shares
  the address "testclient", so dozens of requests tripped the real limiter
  and cascaded 429s into unrelated tests. `tests/conftest.py` now installs an
  effectively unlimited limiter for every test; the limiter's own tests put
  their instance back.
- **Oversized and lying request bodies** — refusing only the declared
  `Content-Length` lets a chunked body or a false header through. The
  middleware now counts bytes as they are read and 413s past
  `MAX_REQUEST_BODY_BYTES` (default 1 MiB), registered innermost so the
  short-circuited response still carries CORS headers a browser can read
  (`tests/test_hardening.py`).
- **Hung and flaky LLM providers** — without a timeout a stalled call pinned
  a worker thread until the client gave up; without retries one dropped
  packet became a failed turn. Both providers now run with
  `LLM_TIMEOUT_SECONDS` (60) and `LLM_MAX_RETRIES` (2).
- **Neon dropping idle connections** — a stale pooled connection failed the
  next query with "SSL connection closed". The engine now uses
  `pool_pre_ping=True`, `pool_recycle` (1800s) and bounded
  `POOL_SIZE`/`POOL_MAX_OVERFLOW`/`POOL_TIMEOUT_SECONDS`.

## 6. Routing issues

- **The "general" route answered off-scope questions badly.** It was first
  constrained to hospital topics (`d3f2777`) and then removed entirely
  (`6d90c5a`): everything falls through to RAG, whose prompt answers
  off-scope questions with "I don't know based on the provided documents."
- **The router classified the raw turn.** Fixed by putting a rewrite node
  ahead of it: the router now classifies `search_query`, the same string
  retrieval searches, so routing and retrieval can no longer disagree about
  what a follow-up means.

## 7. SDK / dependency issues

- **google-genai AFC warning — known, not silenced here.** google-genai 2.x
  enables automatic function calling inside `Models.generate_content` and
  logs a warning recommending `Chat.send_message`, even when no callable
  tools are registered. `langchain_google_genai` always calls
  `generate_content` and exposes no AFC option, so every Gemini call in the
  backend hits it — harmless (logged once per process, nothing executed,
  and this project never relies on SDK-side AFC; tools run in Python via
  LangGraph) but noisy. The fix is `.bind(automatic_function_calling=
  {"disable": True})` on the Gemini model in `backend/app/llm.py`; that
  file currently sets only timeout and retries, so the warning still
  appears.

---

## Recurring themes

1. **Trust boundaries** — prompt injection, RBAC, anonymous access; anything
   the user or a document supplies is data, never instructions, never
   identity.
2. **Statelessness** — in-process state does not survive multiple
   conversations or restarts; relational state belongs in Neon.
3. **Multi-turn understanding** — follow-ups need rewriting and referent
   resolution *before* routing or retrieval can see what the turn means.
4. **Config timing** — secrets and connections must fail at runtime with a
   clear error, never at import time.
5. **Fail closed on identity, fail open on heuristics** — access, roles and
   ownership deny by default; the rewrite and groundedness judge keep an
   answer when their own machinery breaks, because refusing a good answer is
   worse than missing a check.

---

## Still-open rough edges

Known and deliberately deferred — see `plan.md` for the full discussion:

- Past dates are bookable (`check_slot()` has no calendar check; the
  `MONDAY = 2026-09-28` test fixture is now in the past).
- The google-genai AFC warning is not silenced in this tree.
- Up to three LLM calls per turn with history (condense + answer +
  groundedness judge), uncached.
- `PATCH` vs `DELETE` redundancy on `/admin/appointments/{id}` (unsettled).
- `GET /appointments` and `GET /admin/appointments` return identical data
  for an admin.
- Rate limiting is in-process, per worker, keyed on the socket address;
  `X-Forwarded-For` is not trusted, so behind a proxy all callers share one
  bucket. Needs Redis and a trusted-proxy policy before scaling out.
- No token revocation, no refresh tokens; a leaked JWT stays valid until it
  expires.
- No security headers (HSTS, CSP, X-Content-Type-Options).
- History is windowed, not summarised — very old context is forgotten.
- `main.py` and `python -m app.*` / `uvicorn` need `backend` on
  `PYTHONPATH`; there is no Dockerfile here to encode it.
- `CLAUDE.md` is empty and `README.md` has drifted (removed `frontend/`,
  `app/` paths, "78 tests"); the code plus `plan.md` and this file are the
  source of truth.
