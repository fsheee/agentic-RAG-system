# Plan — Agentic RAG System

Status of the build: what exists today, what is left, and what is known to be
imperfect. Kept in sync with the code rather than with the roadmap.

Last updated: 2026-10-16

---

## Where the project stands

Phase 1 (RAG foundation) is complete. Phase 2 (agentic orchestration) covers
the agent, tools, guardrails, rewrite-before-routing, Neon, auth, RBAC,
document access control, conversation memory, booking, groundedness
validation, observability and reliability hardening, the REST surface and
evals. The Next.js frontend in `frontend/` provides the chat interface,
registration, login, and API client; it calls the FastAPI backend and uses
the configured CORS allow-list. What remains is
containers, CI and deployment.

Test suite: **314 passing** (`uv run python -m pytest -q` from the repo root).

The package lives in `backend/app/` (it moved out of `app/` in `1daa609`).
Tests import it as `app.*` because `pyproject.toml` puts `backend` on
pytest's `pythonpath`. Outside pytest, `app.*` resolves only when `backend`
is on `PYTHONPATH` — see "Required setup step".

---

## Done — Phase 1: RAG foundation

| Component | File | Notes |
|---|---|---|
| Document loading | `backend/app/loader.py` | PDF (`PyPDFLoader`) + TXT, from `knowledge_base/` at the repo root; stamps `metadata["access"]` |
| Splitting | `backend/app/splitter.py` | Chunks sized for embedding/retrieval |
| Embeddings | `backend/app/embedding.py` | Configured model, no hard-coded credentials |
| Vector store | `backend/app/vectorstore.py` | Qdrant; local mode anchored to `<repo>/qdrant_data` regardless of cwd (`QDRANT_PATH` overridable) |
| Retrieval | `backend/app/retriever.py` | Threshold + relative-score margin; Qdrant access-tier filter |
| Prompting | `backend/app/prompt.py` | System / history / question / context kept distinct |
| LLM | `backend/app/llm.py` | Env-var credentials only, plus a bounded call budget (below) |
| Ingestion | `backend/app/ingest.py` | Idempotent — deterministic chunk IDs, safe to re-run |
| Reusable core | `backend/app/core.py` | `build_context()` / `format_history()` / `format_sources()` / `ask()` |
| Compat shim | `backend/app/rag_chain.py` | Delegates to `core.ask()`, no second implementation |

Single source of truth for retrieval → context → prompt → LLM. No entry point
reimplements it.

---

## Done — Phase 2: Agentic RAG

### Agent graph

`backend/app/agent/graph.py`, in order:

```
START → guardrail ── blocked ─────────────────────────┐
              │                                       │
              └→ rewrite → router → rag │ database │ booking
                                             │
                                       validate → END
```

- **guardrail** — `check_user_input()` rejects injection attempts; a blocked
  turn skips rewriting and routing entirely and jumps to `validate`.
- **rewrite** — resolves the turn into `search_query` via
  `core.rewrite_query()` **before anything classifies it**. No history means
  no LLM call (first turns and the CLI keep their single-call cost).
- **router** — if the conversation has a booking awaiting yes/no
  (`is_awaiting_confirmation(conversation_id)`), it returns `booking`
  without consulting the LLM, so a bare "yes" can never be re-routed.
  Otherwise the LLM classifies `search_query` (the rewritten query, not the
  raw follow-up) into `rag` / `database` / `booking`; unexpected output
  falls back to `rag`.
- **rag / database / booking** — the routes (below).
- **validate** — an empty answer is a failure, and a RAG answer the
  retrieved context does not support is replaced by
  `I don't know based on the provided documents.` with its sources dropped.

`backend/app/agent/state.py` carries `question`, `search_query`, `route`,
`answer`, `sources`, `documents`, `error`, `user_id`, `user_role`,
`history`, `conversation_id`. Role checks happen in these Python nodes,
never in the LLM.

### Tools

- `backend/app/agent/tools/rag_tool.py` — thin wrapper over `core.ask()`.
  It forwards `search_query`, so retrieval searches exactly what the router
  classified and the condense call is never paid twice.
- `backend/app/agent/tools/db_tool.py` — doctors, specializations, fees,
  schedules from Neon. A fee/detail question that names nobody resolves its
  doctor from the conversation (`referenced_doctor()`: the most recent turn
  naming **exactly one** doctor wins; a directory turn listing several
  resolves to no referent rather than picking one). Specialty questions are
  narrowed through `SPECIALTY_ALIASES` with word-boundary matching.
- `backend/app/agent/tools/booking_tool.py` — the booking subgraph
  (parse → availability → confirmation → book), plus cancel / reschedule /
  listing handling.

### Guardrails

- `backend/app/guardrails.py` — `check_user_input()` screens the incoming
  question; `sanitize_context()` neutralises retrieved chunks **and
  replayed history**. Instructions inside either are data, not commands.

### Neon PostgreSQL

Tables: `user`, `doctor`, `doctorschedule`, `patient`, `appointment`,
`conversation`, `message`, `pendingbooking`. Neon holds relational data;
Qdrant holds vectors. They are not mixed.

### Document access control

- `backend/app/access.py` is the single source of truth: `public` →
  `hospital_info.pdf`, `hospital_policy.pdf`; `staff` → `hr_policy.txt`.
  Unlisted files default to `public`, so adding a file cannot silently
  leak something sensitive — change `DOCUMENT_ACCESS` explicitly.
- Enforced as a Qdrant payload filter at retrieval, so a restricted chunk is
  never retrieved, never enters the prompt, and can never be cited.
- `tiers_for_role(None)` and unknown roles fail closed to `{public}`:
  no identity means least privilege, never "unrestricted".
- **Re-ingestion is required after changing a tier** — chunk IDs derive
  from `(source, page, chunk index)`, not from the tier, so existing Qdrant
  points keep the old payload. Silent, with no error and no failing test.

### Authentication and authorization

- `backend/app/auth.py`, `backend/app/auth_routes.py` — JWT, hashed
  passwords, `POST /auth/register`, `POST /auth/login`, `POST /auth/users`,
  `GET /auth/me`.
- Roles: `patient`, `doctor`, `employee`, `hr`, `admin`.
- RBAC is enforced in Python graph nodes and route dependencies — never by
  the LLM, never from the request body.
- Identity and role always come from the JWT. `/ask` accepts anonymous
  callers; a malformed or expired token is still a 401 rather than a silent
  downgrade to anonymous.

### Conversation memory

- `Conversation` / `Message` in Neon, with crud helpers. A stored turn is
  capped at `MAX_MESSAGE_CHARS` (8000) and a conversation title at 200.
- `get_conversation_for_user()` filters on id **and** owner together. Another
  user's id resolves to `None`, and `/ask` answers **404 rather than 403** so
  the response does not confirm the row exists.
- `POST /ask` takes an optional `conversation_id` and returns one. Anonymous
  callers get no memory at all — supplying an id is a 400 and nothing is read
  or written.
- **Anonymous callers are memory-less by design, and there is no guest
  mechanism.** A guest calls the API with no JWT, reads public documents only
  and is never persisted; signing in starts a new authenticated conversation.
  A signed guest-token scheme (ownerless conversations, token in the response
  body) was designed and deliberately **not** built — nothing in this
  repository has a guest login, so it would have added an id-claiming surface
  for a flow no client uses. Do not add `user_id = NULL` conversations:
  `Conversation.user_id` stays non-nullable, and `get_conversation_for_user()`'s
  owner filter depends on it. A malformed `conversation_id` (0 or negative) is
  a 422, not a 400.
- History reaches the LLM through `AgentState` and the `{history}` prompt
  slot. `core.ask()` never imports the database, and the parameter is
  optional, so `rag_chain` and the golden eval are unaffected.
- Windowed to the last 10 messages (`HISTORY_LIMIT`, limited in the query)
  and capped at 4000 rendered characters (`HISTORY_MAX_CHARS`), oldest
  dropped first. No summarisation.

### Follow-up query rewriting — before routing

- `backend/app/rewriter.py` — `CONDENSE_PROMPT` plus `standalone_query()`,
  the normaliser that turns the model's output into a usable search string.
- The implementation is `core.rewrite_query(question, history)` — **one
  extra LLM call, and only when history exists** — called once by the
  graph's `rewrite` node, ahead of the router. Routing and retrieval then
  see the same resolved query, and `rag_tool` forwards it as `search_query`
  so `build_context()` does not condense a second time.
- Retrieval embeds the rewritten query; the answer prompt still receives
  the question as the user asked it. History reaches generation through the
  `{history}` slot, unchanged.
- Fails open: a failed call, an empty rewrite, or one that was nothing but a
  filtered injection falls back to the original question. Rewriting is an
  optimisation and must never fail a request that could have been answered.
- Untrusted on both ends: history is rendered through `format_history()`
  (already sanitized) and the model's output goes through
  `sanitize_context()` and a 200-character cap before it is embedded.
- One RAG implementation still: the rewrite lives in `core`, so every
  caller that passes history gets it, and no route rewrites on its own.

### Groundedness validation

- `backend/app/groundedness.py` — `is_grounded(answer, documents)` judges a
  generated answer against **the exact blocks the model was shown** using
  `GROUNDING_PROMPT` (a one-word `SUPPORTED` / `UNSUPPORTED` verdict).
  It never retrieves and never generates: generation stays in `core.ask()`.
- Runs in the graph's `validate` node, on the **rag route only**, and only
  when documents were retrieved — a database answer came from Neon and a
  booking answer from the workflow, so neither can be "unsupported by
  context". Empty retrieval is trivially grounded (the answer is already
  the unknown fallback).
- Unsupported → replaced by `UNKNOWN_ANSWER` with `sources` cleared;
  citing documents that do not support what was said is exactly the failure
  being caught.
- **Fails open by design**: an unreachable judge, a non-committal reply or
  an unparsable verdict leaves the answer standing, because a wrong refusal
  discards an answer that may be perfectly fine.
- Costs one extra LLM call per grounded RAG turn.

### Booking state

- `PendingBooking` in Neon, keyed by `conversation_id` (unique).
- There is **no in-process store**: `_pending`, `_pending_by_key`,
  `DEFAULT_KEY` and `reset_pending()` were all removed, with no replacement
  global.
- A row is written whenever a turn established something (doctor, day or
  start) and cleared only on a terminal outcome (booked, declined,
  unavailable) or when the turn learned nothing. Keeping partial progress
  means a turn that only asks for more detail does not discard what it
  parsed. State survives restarts and is shared across workers.
- `awaiting_confirmation` separates a finished request waiting on yes/no from
  a half-built one, and is what makes the router send a bare "yes" to the
  booking route without an LLM call.
- Without a `conversation_id` there is no multi-turn booking state at all,
  rather than a shared default slot.

### Booking actions, availability and listings

- `check_slot()` is still the single availability rule — weekly schedule
  window plus conflict check — shared by the booking workflow,
  reschedules, and `POST /appointments`.
- A taken slot is no longer a dead end: `free_slots_on()` subtracts booked
  appointments from the day's windows and the refusal lists what is still
  open ("Free slots that day: 11:00-12:00, ...").
- Cancel/reschedule intent is typo-tolerant: `matches_action_word()` accepts
  a one-edit misspelling ("cancle", "reshedule") **only when the sentence is
  actually about appointments**, so "cancer" can never read as a cancel.
- Appointment ids are parsed with an anchored regex that rejects bare
  numbers next to ordinal suffixes — "19th oct" or "3rd" can never be taken
  for an id. With no id in the message, candidates are narrowed by the
  doctor and date it does mention; ambiguity asks "Which appointment?" and
  lists them.
- Rescheduling requires the new date **and** time in the same message and
  re-runs `check_slot()` with `exclude_appointment_id` so the appointment
  does not conflict with the slot it is vacating.
- Listings filter to dates from today onward and drop cancelled rows for
  "upcoming"; booking refuses to create an appointment when no patient
  record is linked to the account (fail closed, never the demo patient).

### Date parsing

- Accepts ISO (`2026-09-28`), `DD/MM/YYYY`, `today`/`tomorrow`, weekday names,
  and month names in both orders (`28th Sept 2026`, `September 28, 2026`),
  with optional year and ordinal suffixes.
- An impossible date such as `31 February` yields `None` — the workflow asks
  again rather than booking a wrong day.
- Times require an explicit `am`/`pm`/`hh:mm`, or a bare hour introduced by
  "at", so appointment ids and date parts are not read as times.

### REST endpoints

```
POST   /ask                                  agent; conversation_id optional
POST   /auth/register  /auth/login           public
POST   /auth/users                           admin / hr (role rules apply)
GET    /auth/me                              authenticated

GET    /health                               public liveness probe (DB check)
GET    /doctors                              public
POST   /appointments                         patient — books for self
GET    /appointments                         patient: own · admin: all
GET    /doctors/me/schedule                  doctor, own
GET    /doctors/me/appointments              doctor, own

GET    /admin/appointments                   admin
PATCH  /admin/appointments/{id}              admin
DELETE /admin/appointments/{id}              admin
GET    /admin/doctors/{id}/schedule          admin
PUT    /admin/doctors/{id}/schedule          admin — replaces the week
```

`POST /ask` is the only AI endpoint. Everything else is plain CRUD and adds
no RAG or booking logic of its own; `booking_tool.check_slot()` is the single
availability rule shared by the agent workflow, reschedules and
`POST /appointments`.

### Observability and reliability

All in `backend/app/api.py`, `db.py`, `llm.py`, `config.py`:

- **Logging** — one app logger configured at import (`LOG_LEVEL`, default
  INFO, only when the root logger has no handlers). Each `/ask` turn emits
  a single INFO line: `user`, `conversation`, `route`, `elapsed_ms`,
  `error`. **The question text is never logged.** Rate-limit rejections,
  oversized bodies and health failures log at WARNING/ERROR.
- **`GET /health`** — probes the database with a trivial count query; 200
  `{"status": "ok", "database": "up"}` when it answers, 503
  `{"status": "degraded", "database": "down"}` when it does not, so
  orchestrators can tell "serving" from "up but broken". It does not touch
  Qdrant or the LLM, and it is **exempt from rate limiting** — a throttled
  liveness probe looks like an outage.
- **Rate limiting** — `SlidingWindowRateLimiter`, in-process, one bucket per
  client IP, `RATE_LIMIT_PER_MINUTE` (default 60) per 60-second window.
  Applies to **every path except `/health`**; a full window returns 429
  `{"detail": "Too many requests, slow down."}`. Counters reset on restart —
  abuse damping, not quota accounting. Keyed on the socket peer
  (`request.client.host`); `X-Forwarded-For` is deliberately not trusted.
  `tests/conftest.py` swaps in an effectively unlimited limiter for the
  suite, because every `TestClient` request shares one address.
- **Request-body cap** — `MAX_REQUEST_BODY_BYTES` (default 1 MiB). The
  declared `Content-Length` is the fast path (413 without reading a byte);
  the wrapped `receive()` counts bytes actually read, so chunked bodies and
  lying headers are caught too. The middleware is registered innermost, so
  the short-circuited 413 still passes CORS and browsers can read it.
- **LLM call budget** — `LLM_TIMEOUT_SECONDS` (default 60) and
  `LLM_MAX_RETRIES` (default 2) on both providers (`ChatGroq.request_timeout`,
  Gemini `timeout`), enforced by the provider SDK: a hung call is bounded
  and transient 429/5xx failures are retried instead of surfacing as a
  failed turn.
- **Neon pool** — created lazily in `get_engine()` (a missing
  `DATABASE_URL` is a runtime error at first use, never an import-time
  crash), with `pool_pre_ping=True` so a connection Neon dropped while idle
  is replaced instead of failing the next query, plus `POOL_RECYCLE_SECONDS`
  (1800), `POOL_SIZE` (5), `POOL_MAX_OVERFLOW` (10), `POOL_TIMEOUT_SECONDS`
  (30).
- **Unhandled 500s** — a last-resort handler logs the traceback with a
  `request_id` (the client's `X-Request-ID` if present, else a generated
  12-hex id) and returns `{"detail": "Internal server error.", "request_id": ...}`.
  Expected failures (guardrails, RBAC, not-found) are `HTTPException`s and
  never reach it; no stack trace, query or credential reaches the caller.
- **CORS / payload** — explicit `ALLOWED_ORIGINS` allow-list (comma
  separated, defaults to `localhost:3000`) with credentials on, since
  browsers reject `"*"` + `allow_credentials=True`; GZip for responses
  ≥ 1000 bytes.

### Evals

- `eval/golden_rag.json`, `eval/golden_router.json` (rag 6 / database 5 /
  booking 3), `eval/guardrail_cases.json`, `eval/golden_groundedness.json`,
  covered by `tests/test_eval_*.py`.

### Frontend

- `frontend/` is the Next.js App Router client: `app/page.tsx` contains the
  chat UI, `app/login` and `app/register` provide authentication screens, and
  `lib/auth.tsx` / `lib/api.ts` manage auth state and backend requests.
- The browser talks only to FastAPI. `NEXT_PUBLIC_API_URL` in
  `frontend/.env.local` selects the API base URL; the backend's
  `ALLOWED_ORIGINS` must allow the frontend origin.
- Conversation memory is signed-in only. Anonymous requests omit
  `conversation_id`, and the frontend resets the thread on sign-in/sign-out
  so an id never crosses identities.
- Run locally with `cd frontend`, `npm ci`, copy `.env.example` to
  `.env.local`, then `npm run dev`.

---

## Required setup step

New tables and columns reach Neon through `app.seed`, which runs
`create_all()` (new tables), the explicit `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` migrations in `_add_missing_columns()`, and `_seed_admin()` (the
initial admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD`; skipped when unset or the
account already exists).

Any fresh environment — clone, CI, new Neon branch — needs this before the
API will work, or queries fail with `column ... does not exist`:

```bash
# repo root — app.* needs backend/ on PYTHONPATH (pytest gets it from pyproject.toml)
PYTHONPATH=backend uv run python -m app.seed     # PowerShell: $env:PYTHONPATH="backend"
PYTHONPATH=backend uv run python -m app.ingest   # also required after any access-tier change
PYTHONPATH=backend uv run uvicorn app.api:app --reload
```

`app.ingest` must run with the **repo root** as cwd (it reads
`knowledge_base/`), and `app.seed` works from either directory. Local Qdrant
data is anchored to `<repo>/qdrant_data` by `vectorstore.py`, so the cwd no
longer decides which store you get.

---

## Next

Ordered by dependency; each step should land and be tested before the next.

### 1. Docker

`Dockerfile` for FastAPI, `docker-compose.yml` for FastAPI + Qdrant. Neon
stays managed cloud — no local Postgres container. The `PYTHONPATH=backend`
requirement from the setup step has to be encoded in the image.

### 2. CI/CD

GitHub Actions: lint → tests → Docker build. Must run the `app.seed`
migration against a test database. Note there is currently **no linter
configured** in `pyproject.toml`.

### 3. Deployment

FastAPI + Qdrant hosted; Neon connection string and JWT secret injected as
environment variables — never committed.

---

## Open decisions and known rough edges

- **Up to three LLM calls per turn.** A turn with history pays condense +
  answer; a RAG turn that retrieved documents adds the groundedness judge.
  None of it is cached or batched. The price of rewriting and grounding,
  not a bug — revisit if latency matters.
- **Past dates are still bookable.** `check_slot()` validates the weekly
  window and existing appointments but never the calendar, so "book me last
  Monday" (or a reschedule into last week) is accepted when the weekday
  matches the schedule. The appointment-API fixture hard-codes
  `MONDAY = date(2026, 9, 28)`, now in the past, and the suite stays green
  precisely because nothing rejects it. Recommended: reject `day < today` in
  `check_slot()` and compute the fixture's Monday dynamically. **Not
  implemented.**
- **The google-genai AFC warning is not silenced in this tree.**
  `backend/app/llm.py` sets only timeout/retries; the known fix (`.bind(
  automatic_function_calling={"disable": True})` on the Gemini model) is
  absent, so every Gemini call logs the once-per-process warning. Harmless.
- **`PATCH` vs `DELETE` on `/admin/appointments/{id}`.** The user considers
  one redundant (both can make an appointment disappear). Recommendation was
  to drop `DELETE` and keep `PATCH status=cancelled`, since the codebase
  already models cancellation as a status (`crud.cancel_appointment`) and
  hard-deleting appointment history has audit implications. **Not settled.**
- **`GET /appointments` and `GET /admin/appointments` return identical data
  for an admin.** Kept because both were specified; one could be dropped.
- **History is not summarised.** Very old context is simply forgotten — the
  intended bound, but worth revisiting for long conversations.
- **Rate limiting is in-process and keyed on the socket address.** Counters
  reset on restart and are per worker; behind a reverse proxy every caller
  shares the proxy's IP and therefore one bucket (and `X-Forwarded-For` is
  not trusted, so there is no per-visitor split). Move to Redis with a
  trusted-proxy policy before running more than one worker or instance.
  Still missing entirely: token revocation, refresh tokens — a leaked JWT
  stays valid until it expires.
- **No security headers** (HSTS, CSP, X-Content-Type-Options).
- **Module and CLI entry points need `backend` on `PYTHONPATH`.**
  `main.py` (`from backend.app.core import ask`) fails bare with
  `ModuleNotFoundError: No module named 'app'`, and `python -m app.seed` /
  `uvicorn app.api:app` resolve only from the setup step above. There is no
  Dockerfile yet to encode it. Pytest is unaffected (`pythonpath` in
  `pyproject.toml`).
- **`CLAUDE.md` is empty** (its content was wiped in the working tree), and
  **`README.md` has drifted**: it still documents old `app/` paths and
  "78 tests". The code plus this file and `ISSUE.MD` are
  the source of truth until those are rewritten.

---

## Standing rules

1. Phase 2 stays in this repository and reuses Phase 1.
2. One RAG implementation — `backend/app/core.py` is the only entry point.
3. Ingestion stays idempotent.
4. Qdrant = vectors; Neon = relational data.
5. Retrieved documents **and replayed conversation history** are untrusted.
6. No hard-coded secrets; parameterized queries only.
7. Small changes, tested after each one.
