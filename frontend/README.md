# Frontend — Agentic RAG chat

Next.js App Router client for the FastAPI backend: chat, sign-in, registration,
and the API client. The browser talks only to FastAPI — never to Qdrant,
PostgreSQL, or the LLM provider.

## Local development

```bash
cp .env.example .env.local     # keep exactly ONE NEXT_PUBLIC_API_URL line
npm ci
npm run dev                    # http://localhost:3000
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Base URL of the FastAPI backend (no trailing slash). |

- Local: `http://localhost:8000`.
- Production: `https://agentic-rag-with-gemini-embedding-m.vercel.app`.
- The backend's `ALLOWED_ORIGINS` must include this app's origin, or the
  browser blocks every request.
- The live site does **not** read `.env.local`. Set `NEXT_PUBLIC_API_URL` in
  Vercel → project `agentic-ragsystem` → Settings → Environment Variables,
  then redeploy.

## Production

| Piece | Vercel project | URL |
| --- | --- | --- |
| Frontend | `agentic-ragsystem` | https://agentic-ragsystem.vercel.app |
| Backend | `agentic-rag-with-gemini-embedding-model` | https://agentic-rag-with-gemini-embedding-m.vercel.app |

Deployment runs from `.github/workflows/deploy.yml` on every push to `main`.
See `../README.md`, `../plan.md`, and `../DEPLOYMENT.md` for the full system.
