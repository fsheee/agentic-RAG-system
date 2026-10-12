# Agentic RAG Backend

Backend for a healthcare assistant that answers questions from a hospital
knowledge base, queries relational data, and books appointments. Built as an
**Agentic RAG** system in two layers over one repository:

- **RAG core** — retrieval-augmented answering over hospital documents
  (Qdrant + LLM) with grounded source citations.
- **Agent layer** — a LangGraph agent that routes each question between the
  RAG core, relational data (PostgreSQL), and a multi-step appointment
  booking workflow, served through FastAPI.

The backend also exposes JWT auth, role-based access control, conversation
memory, and plain REST CRUD for doctors and appointments.

> This document covers the **backend only**. There is no frontend in scope
> here; the API is a plain HTTP service consumed by any client.

---

## Architecture

### Request flow

```
                       Client
                         │
                FastAPI (POST /ask)
                         │
                    LangGraph
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
    Guardrail         Router          Validation
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
     RAG Tool      Database Tool      Booking Tool
        │                │                 │
        ▼                ▼                 ▼
   core.py / Qdrant   PostgreSQL      PostgreSQL
        │                          (doctors, schedules,
        ▼                           patients, appointments)
   Answer + Sources
```

The graph runs `START → guardrail → router → rag|database|booking → validate → END`.
Role and identity always come from the signed JWT and are enforced in Python
(graph nodes + the Qdrant retrieval filter) — never by the LLM.

### RAG pipeline

```
knowledge_base/ (PDF/TXT)
  ↓  loader.py     load + attach access tier to metadata
  ↓  splitter.py   chunk 500 / overlap 100
  ↓  embedding.py  all-MiniLM-L6-v2
  ↓  ingest.py     deterministic IDs → idempotent upsert + stale pruning
Qdrant
  ↓  retriever.py  top-k + access filter + relevance thresholds
  ↓  core.py       context → RAG prompt → LLM → answer + citations
Answer + Sources
```

`backend/app/core.py` is the **single reusable RAG entry point**
(`ask(question) -> {answer, sources, documents}`). The CLI, the API, and the
agent's RAG tool all go through it; there is no second RAG implementation.

### Routes

| Route | Handles | Backed by |
| --- | --- | --- |
| `rag` | hospital policies, visiting hours, HR rules, general questions | `rag_tool` → `core.ask()` → Qdrant |
| `database` | doctor list, specializations, consultation fees, doctor details, viewing appointments | `db_tool` → PostgreSQL |
| `booking` | book / cancel / reschedule appointments | `booking_tool` → PostgreSQL |

**Booking is a multi-step workflow** (its own LangGraph subgraph): parse →
check availability (weekly schedule + conflicts) → ask for confirmation →
create the appointment **only after an explicit "yes"**. Pending state is
stored in PostgreSQL keyed by conversation, so a half-finished booking
survives a restart and is shared across workers.

---

## Project layout

```
backend-rag/
├── backend/app/
│   ├── api.py               FastAPI app: /ask, /health, middleware
│   ├── auth.py              bcrypt hashing + JWT helpers
│   ├── auth_routes.py       /auth/* endpoints + role dependencies
│   ├── appointment_routes.py REST CRUD for doctors & appointments
│   ├── access.py            knowledge-base access tiers (public/staff)
│   ├── config.py            env-driven settings (thresholds, offline mode)
│   ├── core.py              single RAG entry point (ask/build_context)
│   ├── crud.py              parameterized DB access
│   ├── db.py                SQLModel engine + session dependency
│   ├── embedding.py         HuggingFace embeddings
│   ├── guardrails.py        injection screening + context sanitization
│   ├── ingest.py            idempotent Qdrant ingestion
│   ├── llm.py               Groq / Gemini client (temperature 0)
│   ├── loader.py            PDF/TXT loading with pseudo-pages
│   ├── prompt.py            RAG prompt
│   ├── retriever.py         top-k retrieval with access + score filters
│   ├── rewriter.py          follow-up → standalone search query
│   ├── schema.py            SQLModel tables
│   ├── seed.py              idempotent sample data + column migrations
│   ├── splitter.py          recursive text splitter
│   ├── vectorstore.py       Qdrant vector store (remote or local)
│   └── agent/
│       ├── graph.py         LangGraph orchestration
│       ├── state.py         typed agent state
│       └── tools/
│           ├── rag_tool.py       delegates to core.ask()
│           ├── db_tool.py        doctors / fees / details
│           └── booking_tool.py   booking workflow + cancel/reschedule
├── knowledge_base/          hospital_info.pdf, hospital_policy.pdf, hr_policy.txt
├── eval/                    golden sets (router, RAG answers, guardrails)
├── tests/                   pytest suite
├── main.py                  Phase-1 CLI (RAG only)
├── pyproject.toml
└── .env.example
```

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A PostgreSQL database (a managed Neon instance works out of the box)
- An LLM API key (Groq or Google Gemini)

---

## Getting started

### 1. Install

```bash
uv sync
# or: pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
```

| Variable | Description | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Groq API key | — |
| `MODEL_NAME` | Groq model | `openai/gpt-oss-120b` |
| `GOOGLE_API_KEY` | Gemini key — when set, the LLM switches to Gemini | — |
| `GEMINI_MODEL` | Gemini model | `gemini-3.1-flash-lite` |
| `EMBEDDING_MODEL` | HuggingFace embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| `DATABASE_URL` | PostgreSQL connection string | — |
| `JWT_SECRET` | HMAC secret for signing tokens | — |
| `JWT_EXPIRE_MINUTES` | Token lifetime | `60` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Initial admin created by the seed script | — |
| `QDRANT_URL` | Qdrant server URL; empty = local mode (`qdrant_data/`) | — |
| `QDRANT_COLLECTION_PREFIX` | Prefix for the Qdrant collection name | — |
| `RETRIEVAL_THRESHOLD` | Minimum relevance score for a chunk to be used | `0.65` |
| `SCORE_MARGIN` | Max score drop from the best match | `0.10` |
| `ALLOWED_ORIGINS` | CORS origins (comma-separated) | `http://localhost:3000,http://127.0.0.1:3000` |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith tracing (optional) | — |

`DATABASE_URL`, `JWT_SECRET`, and an embedding model are required to start.
`GOOGLE_API_KEY` takes precedence over Groq when both are set.

### 3. Ingest the knowledge base

```bash
uv run python -m app.ingest    # idempotent — safe to re-run
```

### 4. Seed the database

Creates tables, applies lightweight column migrations, and inserts sample
doctors, weekly schedules, a demo patient, and the initial admin user.

```bash
uv run python -m app.seed      # idempotent — safe to re-run
```

### 5. Run the API

```bash
uv run uvicorn app.api:app --reload
# run from the repo root; module path is app.api because backend/ is on PYTHONPATH
```

Interactive docs: <http://localhost:8000/docs>

### CLI (RAG only)

```bash
uv run python main.py
```

---

## API reference

Auth is optional on `/ask`; every other endpoint enforces its own
requirements. Pass the JWT as `Authorization: Bearer <token>`.

### Core

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/ask` | optional | Agent entry point (guardrail → route → answer). |
| `GET` | `/health` | none | Liveness probe; `200 ok` when the DB answers, `503 degraded` otherwise. |

`POST /ask` request:

```json
{
  "question": "What are the hospital visiting hours?",
  "conversation_id": null
}
```

`conversation_id` is optional. Supplying one continues that conversation and
**requires a valid token + ownership**; an anonymous caller passing one gets
`400`, and another user's id resolves to `404`.

Response:

```json
{
  "answer": "Visiting hours are 10 AM to 8 PM daily.",
  "sources": [{ "source": "knowledge_base/hospital_policy.pdf", "page": 1 }],
  "conversation_id": 7
}
```

`conversation_id` is `null` for anonymous callers — nothing is persisted
without an identity to scope it to.

### Auth — `/auth`

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | none | Self-register a **patient**. |
| `POST` | `/auth/login` | none | Exchange credentials for a bearer token. |
| `POST` | `/auth/users` | admin / hr | Create staff users with an assigned role. |
| `GET` | `/auth/me` | token | The current user. |

Role assignment is never client-controlled: `/auth/register` always creates a
patient, and `/auth/users` enforces `CREATION_RULES` — admins create
employee/doctor/hr, HR creates employees. Admins are created only by the seed
script, never through the API.

### Doctors

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/doctors` | none | Public doctor directory (name, specialization, fee). |
| `GET` | `/doctors/me/schedule` | doctor | The signed-in doctor's own weekly schedule. |
| `GET` | `/doctors/me/appointments` | doctor | Appointments booked with the signed-in doctor. |

### Appointments

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/appointments` | patient | Book for the signed-in patient's own record. |
| `GET` | `/appointments` | patient / admin | Own appointments (patient) or all (admin). |
| `GET` | `/admin/appointments` | admin | Every appointment. |
| `PATCH` | `/admin/appointments/{id}` | admin | Change date/time/status. |
| `DELETE` | `/admin/appointments/{id}` | admin | Delete an appointment. |
| `GET` | `/admin/doctors/{id}/schedule` | admin | Any doctor's weekly schedule. |
| `PUT` | `/admin/doctors/{id}/schedule` | admin | Replace a doctor's whole week. |

Booking and reschedule both validate the slot through the *same* `check_slot`
logic the agent uses (weekly schedule membership + conflict check), so the
REST API and `/ask` can never disagree about availability. An empty `slots`
list on the schedule PUT clears the schedule and makes the doctor unbookable.

### Example: ask

```bash
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the hospital visiting hours?"}'
```

### Example: authenticated booking

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"patient@example.com","password":"secret123"}' | jq -r .access_token)

curl -X POST http://localhost:8000/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Book an appointment with Dr. Ayesha tomorrow at 10am"}'
# → "Please confirm: appointment with Dr. Ayesha Siddiqui ... Reply 'yes' to confirm."

curl -X POST http://localhost:8000/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"yes","conversation_id":<id from first response>}'
```

---

## Access control

**Document tiers** (`app/access.py`) gate which knowledge-base files a role can
retrieve. The tier is stored in each chunk's metadata and enforced as a Qdrant
payload filter at retrieval time — a restricted chunk is never retrieved, never
enters the prompt, and can never be cited.

| Document | Tier |
| --- | --- |
| `hospital_info.pdf`, `hospital_policy.pdf` | public |
| `hr_policy.txt` | staff |

| Role | Tiers readable |
| --- | --- |
| anonymous (no token) | public |
| patient | public |
| doctor / employee / hr / admin | public + staff |

Unlisted files default to public, so adding a document cannot silently leak or
restrict it — change `DOCUMENT_ACCESS` explicitly for anything sensitive.

**Appointment data** is private: patients reach only their own linked `Patient`
row and doctors only their own linked `Doctor` row (`Patient.user_id` /
`Doctor.user_id`). An unlinked account falls back to nothing, never to the
seeded demo patient. Booking/cancel/reschedule via `/ask` is limited to
patients (their own) and admins; anonymous callers are denied outright.

---

## Key behaviors

- **One RAG implementation.** CLI, API, and agent all reuse `core.ask()`.
- **Idempotent ingestion.** Deterministic chunk IDs mean re-ingestion upserts
  instead of duplicating; vectors from removed documents are pruned.
- **Grounded citations.** The LLM cites only the context blocks it used.
  Retrieved-but-unused chunks are not listed, and an ungrounded answer returns
  `"I don't know based on the provided documents."` with **no** sources.
- **Two-stage retrieval filter.** Chunks below `RETRIEVAL_THRESHOLD` are
  dropped, and chunks scoring more than `SCORE_MARGIN` below the best match are
  dropped too, so loosely related chunks are not cited as support.
- **Follow-up rewriting.** When history is present, the question is rewritten
  into a standalone search query before retrieval ("what about the fees for
  that doctor?"). Fails open to the original question.
- **Untrusted content.** User input is screened for prompt injection; retrieved
  documents and replayed history are sanitized before entering any prompt.
- **Booking needs confirmation.** Availability is checked first; the row is
  created only after an explicit "yes", and re-checked at booking time.
- **Every `/ask` is logged** with user, conversation, route, latency, and error.

---

## Testing

Tests live in `tests/` and exercise each module in isolation (Qdrant, the
database, and LLMs are mocked). About 245 test functions across 25 files.

```bash
uv run pytest -q
```

`pyproject.toml` sets `pythonpath = ["backend", "."]`, so tests import `app.*`
directly. Golden-set evals live in `eval/` and back the `test_eval_*` modules:

| File | Covers |
| --- | --- |
| `test_core.py` / `test_retriever.py` / `test_ingest.py` | RAG core, filtering, idempotency |
| `test_loader.py` / `test_splitter.py` / `test_embedding.py` / `test_vectorstore.py` | Ingestion pipeline |
| `test_guardrails.py` / `test_rewriter.py` / `test_prompt.py` / `test_llm.py` | Prompt boundaries |
| `test_agent.py` / `test_booking_parsing.py` / `test_cancel_intent.py` / `test_db_tool.py` | Agent routing and tools |
| `test_auth.py` / `test_rbac.py` / `test_access.py` | Auth and access tiers |
| `test_api.py` / `test_appointments_api.py` / `test_conversations_api.py` | HTTP endpoints |
| `test_eval_router.py` / `test_eval_retrieval.py` / `test_eval_rag_answers.py` / `test_eval_guardrails.py` | Golden-set evals |

Tests marked `integration` require live Qdrant, PostgreSQL, or an LLM key:

```bash
uv run pytest -q -m "not integration"
```

---

## Deployment notes

This repository is not containerized yet — there is no `Dockerfile` or
`docker-compose.yml` at the root. To run it as a service you need:

- Python 3.11+ with `uv` (or an equivalent image) and `app.*` importable
  (set `PYTHONPATH=backend`)
- A reachable PostgreSQL instance via `DATABASE_URL`
- A reachable Qdrant — remote via `QDRANT_URL`, or a mounted `qdrant_data/`
  volume for local mode

Start command:

```bash
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Create the schema and seed data before the first request:

```bash
python -m app.seed     # tables + sample data
python -m app.ingest   # knowledge base → Qdrant
```

Health checks should target `/health` (returns `503` when the database is
unreachable) rather than `/`, which has no route.

---

## Tech stack

- **FastAPI** — HTTP layer, validation, dependency-injected session/auth
- **LangGraph / LangChain** — agent orchestration and RAG pipeline
- **Qdrant** — vector store (local `qdrant_data/` or remote via `QDRANT_URL`)
- **PostgreSQL** (Neon) — relational data, auth, conversations, pending bookings
- **SQLModel** — schema + ORM
- **Groq / Google Gemini** — LLM inference
- **HuggingFace sentence-transformers** — embeddings
- **PyJWT + bcrypt** — auth
- **uv** — dependency management
