# Agentic RAG System

A healthcare assistant built as an **Agentic RAG** system, developed in two phases in a single repository:

- **Phase 1 — Basic RAG:** retrieval-augmented answering over a hospital knowledge base (Qdrant + LLM) with source citations.
- **Phase 2 — Agentic RAG:** a LangGraph agent that routes questions between the RAG core, relational data (Neon PostgreSQL), and an appointment-booking workflow — exposed through a FastAPI API.

## Architecture

```
                         User
                          │
                       FastAPI (POST /ask)
                          │
                       LangGraph
                          │
                 ┌────────┼─────────────┐
                 │        │             │
             Guardrail  Router      Validation
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
        RAG Tool      Database Tool   Booking Tool
            │             │             │
            ▼             ▼             ▼
   Phase 1 core.py    Neon          Neon (doctors,
   Qdrant retrieval   PostgreSQL    schedules, patients,
                                       appointments)
            │
            ▼
      Answer + Sources
```

### Phase 1 — RAG pipeline

```
knowledge_base/ (PDF/TXT)
  ↓  loader.py
  ↓  splitter.py (chunk 500, overlap 100)
  ↓  embedding.py (all-MiniLM-L6-v2)
  ↓  ingest.py (deterministic IDs → idempotent upsert)
Qdrant
  ↓  retriever.py (top-k + relevance thresholds)
  ↓  core.py (context, prompt, LLM)
Answer + Sources
```

`app/core.py` is the **single reusable RAG entry point** (`ask(question) -> {answer, sources, documents}`). Every consumer — CLI, API, LangGraph nodes — goes through it; there is no second RAG implementation.

### Phase 2 — Agent graph

```
START → Guardrail → Router → rag / database / booking → Validate → END
```

| Route | Handles | Tool |
| --- | --- | --- |
| `rag` | hospital policies, visiting hours, HR rules, general questions | `rag_tool` → `core.ask()` → Qdrant |
| `database` | doctor list, consultation fees, doctor details, viewing appointments | `db_tool` → Neon PostgreSQL |
| `booking` | book / cancel / reschedule appointments | `booking_tool` → Neon PostgreSQL |

**Booking is a multi-step workflow** (its own LangGraph subgraph with state): parse → check availability (schedule + conflicts) → ask for confirmation → create the appointment **only after an explicit "yes"**. Pending state carries across turns.

**Guardrails:** user input is screened for prompt injection before routing, and retrieved documents are treated as untrusted data — instructions inside them are sanitized and never override system instructions.

## Components

| Module | Purpose |
| --- | --- |
| `app/loader.py` | Loads PDF (`PyPDFLoader`) and TXT (line-based pseudo-pages) files from `knowledge_base/` |
| `app/splitter.py` | Recursive text splitter (chunk size 500, overlap 100) |
| `app/embedding.py` | `sentence-transformers/all-MiniLM-L6-v2` embeddings |
| `app/vectorstore.py` | Qdrant vector store (remote via `QDRANT_URL` or local mode), cosine distance |
| `app/retriever.py` | Top-k similarity search with absolute + relative relevance filters |
| `app/ingest.py` | **Idempotent** ingestion: deterministic chunk IDs (upsert, no duplicates) + stale-vector pruning |
| `app/prompt.py` | RAG prompt: answer only from context, numbered blocks, cite used sources, treat documents as data |
| `app/llm.py` | Groq `ChatGroq` or Gemini `ChatGoogleGenerativeAI` (temperature 0) |
| `app/core.py` | Single RAG entry point: `ask()`, `build_context()`, `format_sources()` |
| `app/rag_chain.py` | Compatibility layer delegating to `core.ask()` |
| `app/guardrails.py` | Input screening + context sanitization (prompt-injection protection) |
| `app/schema.py` | SQLModel tables: `Doctor`, `DoctorSchedule`, `Patient`, `Appointment` |
| `app/db.py`, `app/crud.py` | Neon PostgreSQL engine and parameterized CRUD |
| `app/seed.py` | Idempotent sample-data seeding (doctors, schedules, patient, fees) + column migrations |
| `app/agent/graph.py` | LangGraph orchestration: guardrail → router → tools → validation |
| `app/agent/state.py` | Typed agent state |
| `app/agent/tools/rag_tool.py` | Thin tool delegating to `core.ask()` |
| `app/agent/tools/db_tool.py` | Doctors, consultation fees, doctor details (Neon) |
| `app/agent/tools/booking_tool.py` | Multi-step booking workflow + cancel/reschedule/list (Neon) |
| `app/api.py` | FastAPI `POST /ask` |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Neon PostgreSQL database (for the agent's relational data)

### Installation

```bash
git clone <repo-url>
cd agent-rag
uv sync          # or: pip install -e .
```

### Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Description | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Groq API key | — |
| `MODEL_NAME` | Groq model to use | `openai/gpt-oss-120b` |
| `GOOGLE_API_KEY` | Google/Gemini API key (switches LLM to Gemini when set) | — |
| `GEMINI_MODEL` | Gemini model to use | `gemini-3.1-flash-lite` |
| `EMBEDDING_MODEL` | HuggingFace embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| `QDRANT_URL` | Qdrant server URL; empty = local mode (`qdrant_data/`) | — |
| `QDRANT_COLLECTION_PREFIX` | Prefix for the Qdrant collection name | — |
| `DATABASE_URL` | Neon PostgreSQL connection string | — |
| `RETRIEVAL_THRESHOLD` | Minimum relevance score for retrieved chunks | `0.65` |
| `SCORE_MARGIN` | Max score drop from the best match | `0.10` |
| `LANGSMITH_*` | LangSmith tracing (optional) | — |

### Ingest the Knowledge Base

```bash
uv run python -m app.ingest    # idempotent — safe to re-run
```

### Seed the Database

```bash
uv run python -m app.seed      # idempotent — safe to re-run
```

### Run the API

```bash
uv run uvicorn app.api:app --reload
```

Ask a question:

```bash
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the hospital visiting hours?"}'
```

Response:

```json
{
  "answer": "Visiting hours are 10 AM to 8 PM daily.",
  "sources": [
    {"source": "knowledge_base/hospital_policy.pdf", "page": 1}
  ]
}
```

Example questions per route:

- RAG: *"What are the hospital visiting hours?"*, *"What is the probation period?"*
- Database: *"Which doctors are available?"*, *"What are the consultation fees?"*, *"What are the details of Dr. Sarah Ahmed?"*, *"Show my appointments"*
- Booking: *"Book an appointment with Dr. Ayesha tomorrow at 10am"* → availability check → *"Please confirm..."* → *"yes"* → booked

### CLI (Phase 1)

```bash
uv run python main.py
```

## Key Behaviors

- **One RAG implementation.** All entry points (CLI, API, agent) reuse `app/core.py`.
- **Idempotent ingestion.** Deterministic chunk IDs mean re-running ingestion upserts instead of duplicating; removed documents have their stale vectors pruned.
- **Grounded citations.** The LLM cites only the context blocks it actually used — retrieved-but-unused chunks are not listed as sources.
- **Unknown means unknown.** If the context doesn't contain the answer, the system says "I don't know based on the provided documents." — and cites no sources.
- **Booking requires confirmation.** Availability is checked first; the appointment row is created only after an explicit user "yes".
- **Untrusted content.** User input is screened by a guardrail; retrieved documents are sanitized before entering the prompt.

## Testing

The project is developed test-first with pytest. Tests live in `tests/` and exercise each module in isolation (Qdrant, Neon, and LLMs are mocked).

```bash
uv run pytest -q
```

**Current status:** 78 tests — all passing.

| File | Covers |
| --- | --- |
| `tests/test_loader.py` | PDF/TXT loading, pseudo-page metadata |
| `tests/test_splitter.py` | Chunk size, overlap, metadata preservation |
| `tests/test_retriever.py` | Threshold and margin filtering |
| `tests/test_core.py` | `ask()`, context blocks, selective citations |
| `tests/test_ingest.py` | Deterministic IDs, idempotency, stale pruning |
| `tests/test_guardrails.py` | Injection screening and sanitization |
| `tests/test_agent.py` | Routing, RAG/database/booking nodes |
| `tests/test_api.py` | FastAPI `/ask` endpoint |
| `tests/test_eval_*.py` | Golden-set evals (router, retrieval, guardrails) |

## Tech Stack

- **LangChain / LangGraph** — RAG pipeline and agent orchestration
- **Qdrant** — vector database (local mode in `qdrant_data/`, or remote via `QDRANT_URL`)
- **Neon PostgreSQL** — relational data (doctors, schedules, patients, appointments)
- **Groq / Gemini** — hosted LLM inference
- **HuggingFace sentence-transformers** — embeddings
- **FastAPI** — REST API
- **uv** — dependency management

## Roadmap

Per `CLAUDE.md`, remaining Phase 2 stages: authentication (JWT/OAuth2), conversation memory in Neon, Next.js frontend, Docker, CI/CD, deployment.
