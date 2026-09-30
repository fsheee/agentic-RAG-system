# Plan — Agentic RAG System

Status of the build: what exists today, what is left, and what is known to be
imperfect. Kept in sync with the code rather than with the roadmap.

Last updated: 2026-10-01

---

## Where the project stands

Phase 1 (RAG foundation) is complete. Phase 2 (agentic orchestration) covers
the agent, tools, guardrails, routing, Neon, auth, RBAC, document access
control, conversation memory, the REST surface and evals. What remains is
frontend, containers, CI and deployment.

Test suite: **206 passing** (`uv run pytest -q`).

---

## Done — Phase 1: RAG foundation

| Component | File | Notes |
|---|---|---|
| Document loading | `app/loader.py` | PDF (`PyPDFLoader`) + TXT, from `knowledge_base/`; stamps `metadata["access"]` |
| Splitting | `app/splitter.py` | Chunks sized for embedding/retrieval |
| Embeddings | `app/embedding.py` | Configured model, no hard-coded credentials |
| Vector store | `app/vectorstore.py` | Qdrant, local `qdrant_data/` mode |
| Retrieval | `app/retriever.py` | Threshold + relative-score margin; Qdrant access-tier filter |
| Prompting | `app/prompt.py` | System / history / question / context kept distinct |
| LLM | `app/llm.py` | Env-var credentials only |
| Ingestion | `app/ingest.py` | Idempotent — deterministic chunk IDs, safe to re-run |
| Reusable core | `app/core.py` | `build_context()` / `format_history()` / `format_sources()` / `ask()` |
| Compat shim | `app/rag_chain.py` | Delegates to `core.ask()`, no second implementation |

Single source of truth for retrieval → context → prompt → LLM. No entry point
reimplements it.

---

## Done — Phase 2: Agentic RAG

### Agent and tools

- `app/agent/graph.py` — LangGraph: guardrail → router → RAG / database /
  booking → generate → validate.
- `app/agent/state.py` — typed state, including `history` and `conversation_id`.
- `app/agent/tools/rag_tool.py` — thin wrapper over `core.ask()`.
- `app/agent/tools/db_tool.py` — parameterized queries against Neon.
- `app/agent/tools/booking_tool.py` — book / cancel / reschedule / list.

### Guardrails

- `app/guardrails.py` — `check_user_input()` screens the incoming question;
  `sanitize_context()` neutralises retrieved chunks **and replayed history**.
  Instructions inside either are data, not commands.

### Neon PostgreSQL

Tables: `user`, `doctor`, `doctorschedule`, `patient`, `appointment`,
`conversation`, `message`, `pendingbooking`. Neon holds relational data;
Qdrant holds vectors. They are not mixed.

### Document access control

- `app/access.py` is the single source of truth: `public` →
  `hospital_info.pdf`, `hospital_policy.pdf`; `staff` → `hr_policy.txt`.
- Enforced as a Qdrant payload filter at retrieval, so a restricted chunk is
  never retrieved, never enters the prompt, and can never be cited.
- `tiers_for_role(None)` and unknown roles fail closed to `{public}`:
  no identity means least privilege, never "unrestricted".
- **Re-ingestion is required after changing a tier**
  (`uv run python -m app.ingest`) — chunk IDs derive from
  `(source, page, chunk index)`, not from the tier, so existing Qdrant points
  keep the old payload. Silent, with no error and no failing test.

### Authentication and authorization

- `app/auth.py`, `app/auth_routes.py` — JWT, hashed passwords,
  `POST /auth/register`, `POST /auth/login`, `POST /auth/users`,
  `GET /auth/me`.
- Roles: `patient`, `doctor`, `employee`, `hr`, `admin`.
- RBAC is enforced in Python graph nodes and route dependencies — never by
  the LLM, never from the request body.
- Identity and role always come from the JWT. `/ask` accepts anonymous
  callers; a malformed or expired token is still a 401 rather than a silent
  downgrade to anonymous.

### Conversation memory

- `Conversation` / `Message` in Neon, with crud helpers.
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
  body) was designed and deliberately **not** built — the frontend has no guest
  login, so it would have added an id-claiming surface for a flow nothing uses.
  Do not add `user_id = NULL` conversations: `Conversation.user_id` stays
  non-nullable, and `get_conversation_for_user()`'s owner filter depends on it.
  A malformed `conversation_id` (0 or negative) is a 422, not a 400.
- History reaches the LLM through `AgentState` and the `{history}` prompt
  slot. `core.ask()` never imports the database, and the parameter is
  optional, so the CLI, `rag_chain` and the golden eval are unaffected.
- Windowed to the last 10 messages (limited in the query) and capped at 4000
  rendered characters, oldest dropped first. No summarisation.

### Booking state

- `PendingBooking` in Neon, keyed by `conversation_id` (unique).
- There is **no in-process store**: `_pending`, `_pending_by_key`,
  `DEFAULT_KEY` and `reset_pending()` were all removed, with no replacement
  global.
- A row is written whenever a turn established something (doctor, day or
  start) and cleared only on a terminal outcome (booked, declined,
  unavailable). Keeping partial progress means a turn that only asks for
  more detail does not discard what it parsed.
- `awaiting_confirmation` separates a finished request waiting on yes/no from
  a half-built one, so the router does not treat an unrelated next question
  as the answer to a confirmation.
- Without a `conversation_id` there is no multi-turn booking state at all,
  rather than a shared default slot.

### Date parsing

- Accepts ISO (`2026-09-28`), `DD/MM/YYYY`, `today`/`tomorrow`, weekday names,
  and month names in both orders (`28th Sept 2026`, `September 28, 2026`),
  with optional year and ordinal suffixes.
- An impossible date such as `31 February` yields `None` — the workflow asks
  again rather than booking a wrong day.

### REST endpoints

```
POST   /ask                                  agent; conversation_id optional
POST   /auth/register  /auth/login           public
POST   /auth/users                           admin / hr (role rules apply)
GET    /auth/me                              authenticated

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

### Evals

- `eval/golden_rag.json`, `eval/golden_router.json`,
  `eval/guardrail_cases.json`, covered by `tests/test_eval_*.py`.

### Frontend

- `frontend/` — Next.js (App Router) chat UI: `app/page.tsx` renders answers
  with their cited sources, plus `app/login` and `app/register`.
  `lib/auth.tsx` holds the token and `lib/api.ts` is the **single door** to the
  backend — the frontend never talks to Qdrant, Neon or the LLM provider.
- Conversation memory is signed-in only, matching the API: an anonymous visitor
  sends *no* `conversation_id`, and the thread resets on sign-in and sign-out so
  an id never crosses identities.
- CORS is an explicit `ALLOWED_ORIGINS` allow-list rather than a wildcard, since
  browsers reject `"*"` combined with `allow_credentials=True`.
- `frontend/.gitignore` keeps `node_modules/`, `.next/` and `.env.local` out of
  the repository.

---

## Required setup step

New tables and columns reach Neon through `uv run python -m app.seed`, which
runs `create_all()` (new tables) plus the explicit `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS` migrations in `_add_missing_columns()`.

Any fresh environment — clone, CI, new Neon branch — needs this before the
API will work, or queries fail with `column ... does not exist`:

```
uv run python -m app.seed    # creates missing tables/columns
uv run python -m app.ingest  # required after any access-tier change
```

---

## Next

Ordered by dependency; each step should land and be tested before the next.

### 1. Follow-up query rewriting

The weakest part of conversation memory. Retrieval still embeds the raw
question, so *"what about the fees for that doctor?"* searches for that
literal string and retrieves poorly. History informs the answer but does not
rewrite the query. A condense step (one extra LLM call + prompt) is the fix.

### 2. Docker

`Dockerfile` for FastAPI, `docker-compose.yml` for FastAPI + Qdrant. Neon
stays managed cloud — no local Postgres container.

### 3. CI/CD

GitHub Actions: lint → tests → Docker build. Must run the `app.seed`
migration against a test database. Note there is currently **no linter
configured** in `pyproject.toml`.

### 4. Deployment

FastAPI + Qdrant hosted; Neon connection string and JWT secret injected as
environment variables — never committed.

---

## Open decisions and known rough edges

- **`PATCH` vs `DELETE` on `/admin/appointments/{id}`.** The user considers
  one redundant (both can make an appointment disappear). Recommendation was
  to drop `DELETE` and keep `PATCH status=cancelled`, since the codebase
  already models cancellation as a status (`crud.cancel_appointment`) and
  hard-deleting appointment history has audit implications. **Not settled.**
- **`GET /appointments` and `GET /admin/appointments` return identical data
  for an admin.** Kept because both were specified; one could be dropped.
- **History is not summarised.** Very old context is simply forgotten — the
  intended bound, but worth revisiting for long conversations.
- **No rate limiting, no token revocation, no refresh tokens.**
- **`CLAUDE.md` no longer documents the access-control or appointment-ownership
  rules** — it was reverted to an earlier form. Re-add if that documentation is
  wanted; the code is the source of truth in the meantime.

---

## Standing rules

1. Phase 2 stays in this repository and reuses Phase 1.
2. One RAG implementation — `app/core.py` is the only entry point.
3. Ingestion stays idempotent.
4. Qdrant = vectors; Neon = relational data.
5. Retrieved documents **and replayed conversation history** are untrusted.
6. No hard-coded secrets; parameterized queries only.
7. Small changes, tested after each one.
