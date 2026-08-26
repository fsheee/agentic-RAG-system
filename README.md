# Agent-RAG

A Retrieval-Augmented Generation (RAG) agent that answers questions from a hospital knowledge base using LangChain, Qdrant, and Groq or Gemini LLMs.

## Architecture

```
PDF/TXT
  ↓
Loader
  ↓
Chunks
  ↓
Embeddings
  ↓
Qdrant
  ↓
Retriever ←── User Question
  ↓
Context
  ↓
Prompt
  ↓
Groq LLM
  ↓
Answer + Sources
```

## Pipeline

1. **Ingestion** (`app/ingest.py`) — Loads documents from `knowledge_base/`, splits them into chunks, and stores them in Qdrant.
2. **Retrieval** (`app/retriever.py`) — Finds the top-k most relevant chunks using vector similarity search.
3. **Generation** (`app/rag_chain.py`) — Feeds retrieved context to the LLM, which answers only from that context, then appends a list of the source documents used. Retrieval/LLM errors are caught and returned as a friendly message instead of a crash.

## Components

| Module | Purpose |
| --- | --- |
| `app/loader.py` | Loads PDF (`PyPDFLoader`) and TXT (`TextLoader`) files from `knowledge_base/` |
| `app/splitter.py` | Recursive text splitter (chunk size 500, overlap 100) |
| `app/embedding.py` | `sentence-transformers/all-MiniLM-L6-v2` embeddings |
| `app/vectorstore.py` | Qdrant vector store (remote via `QDRANT_URL` or local mode), collection `hospital_knowledge` (prefixed by `QDRANT_COLLECTION_PREFIX`), cosine distance |
| `app/retriever.py` | Similarity search (top-3 by default) |
| `app/llm.py` | Groq `ChatGroq` or Gemini `ChatGoogleGenerativeAI` (temperature 0) |
| `app/rag_chain.py` | Composes retrieval + LLM prompt into an answer, appends de-duplicated source citations (file + page), and handles errors gracefully |
| `app/prompt.py` | `ChatPromptTemplate` used by `rag_chain.py` for answer generation |
| `app/config.py` | Central config: loads `.env` (API key, model names), HF offline-mode cache detection |
| `app/ingest.py` | Runs the full ingestion pipeline (load → split → store in Qdrant) |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
git clone <repo-url>
cd agent-rag
uv sync          # or: pip install -e .
```

### Configuration

Copy `.env.example` to `.env` and set your Groq and/or Google API keys:

```bash
cp .env.example .env
```

| Variable | Description | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Your Groq API key | — |
| `MODEL_NAME` | Groq model to use | `openai/gpt-oss-120b` |
| `GOOGLE_API_KEY` | Your Google/Gemini API key (switches LLM to Gemini when set) | — |
| `GEMINI_MODEL` | Gemini model to use | `gemini-3.1-flash-lite` |
| `EMBEDDING_MODEL` | HuggingFace embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| `QDRANT_URL` | Qdrant server URL; empty = local mode (`qdrant_data/`) | — |
| `QDRANT_COLLECTION_PREFIX` | Prefix for the Qdrant collection name | — |

### Add Knowledge

Place your PDF/TXT documents in `knowledge_base/`.

### Ingest Documents

```bash
uv run python -m app.ingest
```

### Test Retrieval

```bash
uv run python -m app.retriever
```

### Generate an Answer

Run the interactive CLI:

```bash
uv run python main.py
```

Or call `generate_answer` directly:

```bash
uv run python -c "from app.rag_chain import generate_answer; print(generate_answer('What is the probation period?'))"
```

### Answer sources (citations)

Every answer ends with a **Sources** section listing the knowledge-base documents the answer was drawn from, including the page number for PDFs. This lets you trace each answer back to its original document and verify it. For example:

```text
Answer:
ABC Healthcare Hospital

Sources:
- knowledge_base/hospital_info.pdf — page 1
- knowledge_base/hr_po
licy.txt
```

The citations are built by `generate_answer` (`app/rag_chain.py`) from the `metadata` of the retrieved chunks: it reads each chunk's `source` (file path) and `page`, converts the page to 1-based numbering, removes duplicates, and appends the list to the answer. If retrieval or the LLM call fails, `generate_answer` catches the error and returns a short apology instead of raising.

## Testing (TDD)

The project is developed test-first with pytest. Tests live in `tests/` and exercise each module in isolation (external services like Qdrant and LLMs are mocked).

### Run the suite

```bash
uv sync          # install dev dependencies (pytest)
uv run pytest    # run all tests
uv run pytest -q
```

**Current status:** 27 tests — all passing. Run the suite to verify before committing.

### Test layout

| File | Covers |
| --- | --- |
| `tests/test_loader.py` | PDF/TXT loading, unsupported files, UTF-8 |
| `tests/test_splitter.py` | Chunk size, overlap, metadata preservation |
| `tests/test_prompt.py` | Prompt rendering and answer-from-context rule |
| `tests/test_rag_chain.py` | Answer generation, Gemini list-content handling |
| `tests/test_llm.py` | Groq vs Gemini provider selection |
| `tests/test_vectorstore.py` | Local/remote Qdrant, collection naming, auto-create |
| `tests/test_embedding.py` | Embedding model config and error handling |

### Workflow

1. Write a failing test for the behavior you want.
2. Run `uv run pytest tests/test_<module>.py` and watch it fail.
3. Implement the feature until the test passes.
4. Run the full suite to confirm nothing else broke.

## Tech Stack

- **LangChain** — document loading, splitting, vector store, LLM wrappers
- **Qdrant** — vector database (local mode stored in `qdrant_data/`, or a remote server via `QDRANT_URL`)
- **Groq / Gemini** — hosted LLM inference
- **HuggingFace sentence-transformers** — embeddings
- **uv** — dependency management

## Notes

- With `QDRANT_URL` unset, Qdrant runs in local embedded mode and data persists under `qdrant_data/` (git-ignored).
- If `QDRANT_URL` is set (e.g. `http://localhost:6333`), a Qdrant server must be running, e.g. `docker run -p 6333:6333 qdrant/qdrant`.
- The retriever is set to return the top 3 documents (`k=3`).
- The model only answers from the retrieved context; if the context lacks an answer, it says it doesn't know.
- Each answer is followed by a **Sources** list (file, plus page number for PDFs) identifying the documents it used.