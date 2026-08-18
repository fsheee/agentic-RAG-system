# Agent-RAG

A Retrieval-Augmented Generation (RAG) agent that answers questions from a hospital knowledge base using LangChain, Qdrant, and Groq's LLM.

## Architecture

```
                    KNOWLEDGE BASE
                         │
                         ▼
              Loader (PDF / TXT)
                         │
                         ▼
                      Splitter
                         │
                         ▼
                     Embeddings
                         │
                         ▼
                       Qdrant
                         │
                         ▼
                      Retriever
                         ▲
                         │
Question ────────────────┘
                         │
                         ▼
                      Context
                         │
                         ▼
                    LLM (Groq)
                         │
                         ▼
                       Answer-
```

## Pipeline

1. **Ingestion** (`app/ingest.py`) — Loads documents from `knowledge_base/`, splits them into chunks, and stores them in Qdrant.
2. **Retrieval** (`app/retriever.py`) — Finds the top-k most relevant chunks using vector similarity search.
3. **Generation** (`app/rag_chain.py`) — Feeds retrieved context to the LLM, which answers only from that context.

## Components

| Module | Purpose |
| --- | --- |
| `app/loader.py` | Loads PDF (`PyPDFLoader`) and TXT (`TextLoader`) files from `knowledge_base/` |
| `app/splitter.py` | Recursive text splitter (chunk size 500, overlap 100) |
| `app/embedding.py` | `sentence-transformers/all-MiniLM-L6-v2` embeddings |
| `app/vectorstore.py` | Qdrant vector store (local mode), collection `hospital_knowledge`, cosine distance |
| `app/retriever.py` | Similarity search (top-3 by default) |
| `app/llm.py` | Groq `ChatGroq` LLM (temperature 0) |
| `app/rag_chain.py` | Composes retrieval + LLM prompt into an answer |

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

Copy `.env.example` to `.env` and set your Groq API key:

```bash
cp .env.example .env
```

| Variable | Description | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Your Groq API key | — |
| `MODEL_NAME` | Groq model to use | `llama-3.3-70b-versatile` |

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

```bash
uv run python -c "from app.rag_chain import generate_answer; print(generate_answer('What is the probation period?'))"
```

## Tech Stack

- **LangChain** — document loading, splitting, vector store, LLM wrappers
- **Qdrant** — vector database (embedded/local, stored in `qdrant_data/`)
- **Groq** — hosted LLM inference
- **HuggingFace sentence-transformers** — embeddings
- **uv** — dependency management

## Notes

- Qdrant runs in local embedded mode; data persists under `qdrant_data/` (git-ignored).
- The retriever is set to return the top 3 documents (`k=3`).
- The model only answers from the retrieved context; if the context lacks an answer, it says it doesn't know.