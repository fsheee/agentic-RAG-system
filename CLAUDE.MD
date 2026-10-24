# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

An **Agentic RAG** healthcare assistant in two phases, one repo:

- **Phase 1 — RAG:** retrieval-augmented answering over `knowledge_base/` (Qdrant + LLM) with source citations.
- **Phase 2 — Agentic:** a LangGraph agent that routes each turn between RAG, relational data (Neon PostgreSQL), and an appointment-booking workflow, exposed as a FastAPI API.

The Python package lives in `backend/app/`; the Next.js client lives in
`frontend/`. The frontend calls the FastAPI API only; keep its
`NEXT_PUBLIC_API_URL` and the backend `ALLOWED_ORIGINS` configuration aligned.

`plan.md` is the authoritative status of the build; `ISSUE.MD` records the problems solved and the open rough edges. Read both before making non-trivial changes. `README.md` documents setup for both frontend and backend; consult `plan.md` for current implementation status.

## Commands

Run from the **repo root**. Every non-pytest command needs `backend` on `PYTHONPATH` (`app.*` does not resolve otherwise):

```bash
export PYTHONPATH=backend            # PowerShell: $env:PYTHONPATH="backend"

uv run python -m pytest -q           # full suite (pytest gets the path from pyproject.toml)
uv run python -m app.seed            # create tables/columns + initial admin (idempotent)
uv run python -m app.ingest          # ingest knowledge_base/ (idempotent; run from repo root)
uv run uvicorn app.api:app --reload  # run the API
uv run python main.py                # Phase 1 CLI
```

Frontend: from `frontend/`, run `npm ci`, copy `.env.example` to
`.env.local`, set `NEXT_PUBLIC_API_URL` if the API is not at
`http://localhost:8000`, then run `npm run dev`.

There is no linter configured. Tests mock Qdrant, Neon, and LLMs; `tests/conftest.py` installs an effectively unlimited rate limiter for the suite (every `TestClient` request shares one address).

## Architecture

### Agent graph — `backend/app/agent/graph.py`

```
START → guardrail ── blocked ───────────────────────┐
              │                                     │
              └→ rewrite → router → rag │ database │ booking → validate → END
```

- **guardrail** — `check_user_input()` rejects injection; a blocked turn skips rewrite/routing and jumps to `validate`.
- **rewrite** — resolves the turn into `search_query` **before** the router classifies it (no history → no LLM call). This ordering is deliberate: routing and retrieval must see the same resolved query.
- **router** — if a booking awaits yes/no, returns `booking` without an LLM call; otherwise classifies `search_query` into `rag` / `database` / `booking` (unknown output → `rag`).
- **validate** — empty answer is a failure; an ungrounded RAG answer is replaced with `UNKNOWN_ANSWER` and its sources dropped.

State (`agent/state.py`) carries `question, search_query, route, answer, sources, documents, error, user_id, user_role, history, conversation_id`. **Role checks run in these Python nodes and route dependencies — never in the LLM, never from the request body.**

### RAG core — `backend/app/core.py` is the ONLY entry point

`ask()` / `build_context()` / `rewrite_query()` / `format_history()` / `format_sources()`. API, agent nodes, `rag_chain` (compat shim), and the CLI all go through it. **Never write a second RAG implementation** — put shared logic in `core`, not in a route.

### Data split

- **Qdrant** = vectors (`qdrant_data/` anchored to repo root via `QDRANT_PATH`, cwd-independent).
- **Neon** = relational (`user`, `doctor`, `doctorschedule`, `patient`, `appointment`, `conversation`, `message`, `pendingbooking`).
- Never mixed.

### Trust boundaries (the recurring theme)

- User input is screened by `guardrails.check_user_input()`.
- Retrieved documents **and replayed conversation history** are untrusted: sanitized with `sanitize_context()` / `format_history()` (the latter deliberately *not* via `check_user_input()`, which would abort every later turn).
- The groundedness judge (`groundedness.py`) is told its context/answer are data, not instructions.
- Identity and role always come from the JWT. A malformed/expired token is a **401**, never a silent downgrade to anonymous; only a *missing* header is anonymous.
- Ownership checks filter on **id AND owner**; a foreign id is a **404, not 403**.
- Access tiers (`access.py`) fail closed (`tiers_for_role(None)` → `{public}`) and are enforced as a Qdrant payload filter at retrieval.

## Conventions

1. **One RAG implementation** — everything routes through `core.py`.
2. **Ingestion stays idempotent** — chunk IDs derive from `(source, page, chunk_index)`; re-running upserts, never duplicates. **After changing a document's access tier you must re-ingest** — the tier is not part of the chunk ID, so existing points keep the old payload. Silent, no error.
3. **Qdrant = vectors; Neon = relational data.**
4. **No hard-coded secrets; parameterized queries only.**
5. **Fail closed on identity, fail open on heuristics** — access/roles/ownership deny by default; the rewrite and groundedness judge keep the answer when their own machinery breaks, because refusing a good answer is worse than missing a check.
6. **Config fails at runtime, not import time** — no work at module import that needs a secret or connection (`DATABASE_URL` is checked at first engine use). Applies to Qdrant/Neon/LLM credentials.
7. **Small changes, tested after each one.** New tables/columns reach Neon through `app.seed`, not by hand.

## Gotchas

- **`PYTHONPATH=backend` is not optional** outside pytest. `main.py` and `python -m app.*` fail bare with `ModuleNotFoundError: No module named 'app'`. Encoding this for deployment is a pending item (no Dockerfile yet).
- **Booking state lives in Neon** (`PendingBooking`, unique `conversation_id`) — there is no in-process store and no shared default slot. Without a `conversation_id` there is no multi-turn booking state.
- **Date/time parsing is strict on purpose**: bare numbers are never times (need `am`/`pm`, `hh:mm`, or an "at"-hour) and never appointment ids (id regex is anchored, rejects ordinals). `31 February` → `None` → asks again.
- **Grounding is rag-route only**, and only when documents were retrieved. It costs an extra LLM call per grounded turn (up to three per turn with history, uncached).
- **`check_slot()` is the single availability rule** shared by the agent workflow, reschedules, and `POST /appointments`. It has no calendar check — past dates are still bookable (known, deliberately deferred).
- **The `/ask` log line never includes the question text.** Keep it that way.
- Rate limiting is in-process, keyed on the socket address; `X-Forwarded-For` is deliberately not trusted.

## Tests & evals

Tests are in `tests/` (pytest, per-module, external services mocked). Golden eval sets live in `eval/` (`golden_rag.json`, `golden_router.json`, `guardrail_cases.json`, `golden_groundedness.json`) and are exercised by `tests/test_eval_*.py`. Integration tests are marked `integration` (need live Qdrant/Neon/LLM).

Run the suite before and after changes: `uv run python -m pytest -q`.
