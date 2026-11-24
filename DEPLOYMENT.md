# Deployment

How the Agentic RAG system is built, released, and verified on Vercel.
The backend and frontend are two separate Vercel projects driven by one GitHub
Actions workflow.

Last verified: 2026-11-24 — backend `/health` returned
`{"status":"ok","database":"up"}` and the frontend loaded.

---

## Live environments

| Piece | Vercel project | URL |
| --- | --- | --- |
| Backend (FastAPI) | `agentic-rag-with-gemini-embedding-model` | https://agentic-rag-with-gemini-embedding-m.vercel.app |
| Frontend (Next.js) | `agentic-ragsystem` | https://agentic-ragsystem.vercel.app |

- API docs: <https://agentic-rag-with-gemini-embedding-m.vercel.app/docs>
- Health probe: <https://agentic-rag-with-gemini-embedding-m.vercel.app/health>

There is no Dockerfile. Vercel builds the backend from `pyproject.toml`
(`[tool.vercel] entrypoint = "backend.app.api:app"`) and the frontend from
`frontend/`.

---

## Release flow

`.github/workflows/deploy.yml` runs on every push to `main` (and manually via
**workflow_dispatch**):

```
test ──► preflight (Vercel credentials) ──► deploy-backend
                                      └───► deploy-frontend
```

1. **test** — `uv sync --frozen`, then `pytest -m "not integration"` with a
   throwaway `JWT_SECRET`. No external service is contacted.
2. **preflight** — fails early and explicitly when `VERCEL_TOKEN` or
   `VERCEL_ORG_ID` is missing, contains whitespace, or is rejected by
   `vercel whoami`.
3. **deploy-backend** — `vercel pull` → `vercel build --prod` → Python-ABI
   check → `vercel deploy --prebuilt --prod`.
4. **deploy-frontend** — same pull/build/deploy with
   `NEXT_PUBLIC_API_URL` inlined into the client bundle.

Pull requests and non-`main` branches are covered by `ci.yml` (backend tests,
throwaway-Postgres schema tests, frontend lint/build, workflow YAML parse), so
the suite does not run twice per merge.

---

## GitHub configuration

Repository **Settings → Secrets and variables → Actions**.

Secrets (the **Secrets** tab, not Variables):

| Name | Value |
| --- | --- |
| `VERCEL_TOKEN` | Vercel token with access to the team. No spaces or newlines. |
| `VERCEL_ORG_ID` | `team_OuVuWFb4CX4GlaWa2YbnNyAC` |

Optional repository **variable**:

| Name | Purpose |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Overrides the frontend's backend URL. Defaults to the deployed backend. |

Project IDs are not credentials and are inlined in `deploy.yml`:

- backend `prj_XoGPPcXH1nFTEUgMI5uXzUf0l4Rc`
- frontend `prj_r8m4yQg5A7HKqjcrcEyZlQ4oNCiT`

Both deploy jobs target the GitHub environment **production**, so protection
rules (required reviewers, wait timers) can be added there.

---

## Vercel environment variables

Set these in the Vercel dashboard, never in the repository.

### Backend project

| Variable | Notes |
| --- | --- |
| `PYTHONPATH` | `backend` — required for `app.*` imports. |
| `DATABASE_URL` | Neon connection string (`?sslmode=require`). |
| `JWT_SECRET` | HMAC secret; the API raises without it. |
| `GOOGLE_API_KEY` | Gemini key. When set, the LLM and default embeddings use Gemini. |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001`. Keep it identical between ingest and serving. |
| `QDRANT_URL` | Qdrant Cloud URL. |
| `QDRANT_API_KEY` | Qdrant Cloud key. |
| `ALLOWED_ORIGINS` | `https://agentic-ragsystem.vercel.app` (exact origin, no trailing slash). |
| `UV_PYTHON` | `3.14` — must match `.python-version`. |

Optional: `MODEL_NAME`, `GEMINI_MODEL`, `QDRANT_COLLECTION_PREFIX`,
`RETRIEVAL_THRESHOLD`, `SCORE_MARGIN`, pool tuning, `LLM_TIMEOUT_SECONDS`,
`LLM_MAX_RETRIES`, `RATE_LIMIT_PER_MINUTE`, `MAX_REQUEST_BODY_BYTES`,
`LOG_LEVEL`, LangSmith variables.

### Frontend project

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Backend base URL, no trailing slash. Inlined at build time — redeploy after changing it. |

---

## Python version and the ABI trap

`.python-version`, `UV_PYTHON`, and the Vercel project's Production
`UV_PYTHON` must all be **3.14**.

If they drift, `uv` installs wheels for one interpreter while the function
runtime uses another. Compiled extensions then fail at cold start with:

```text
ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'
```

`deploy.yml`'s **Check Python ABI** step reads `.vercel/output/functions/*/
.vc-config.json`, resolves the expected `cpython-3XX` ABI, and fails the build
when `_pydantic_core` has no matching `.so`.

---

## First deployment of a new environment

The workflow deploys code; it never creates schema or vectors. Run these once
against production, from the repo root, with production credentials in the
environment:

```bash
export PYTHONPATH=backend          # PowerShell: $env:PYTHONPATH="backend"
python -m app.seed                 # tables, columns, initial admin
python -m app.ingest               # knowledge_base/ → Qdrant
```

Requirements for the one-time run:

- `DATABASE_URL`, `JWT_SECRET`, `GOOGLE_API_KEY`, `EMBEDDING_MODEL`,
  `QDRANT_URL`, `QDRANT_API_KEY` set to the **production** values.
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` if the initial admin should be created.
- `app.ingest` runs with the repo root as cwd (it reads `knowledge_base/`).
- Re-run `app.ingest` after any document or access-tier change.

Then push to `main`, or run the **Deploy** workflow manually.

---

## Verification checklist

```bash
curl https://agentic-rag-with-gemini-embedding-m.vercel.app/health
# {"status":"ok","database":"up"}

curl -X POST https://agentic-rag-with-gemini-embedding-m.vercel.app/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What are the hospital visiting hours?"}'
```

- `/health` returns `200` with `database: "up"` (a `503` means Postgres is
  unreachable, not that the function is down).
- `/ask` returns an answer with sources.
- The frontend loads, signs in, and returns an answer — a CORS failure here
  means `ALLOWED_ORIGINS` does not exactly match the frontend origin.
- Vercel → Deployments shows a successful production build for both projects.

---

## Rollback

Vercel keeps every deployment. In the dashboard, open the project →
**Deployments** → pick the last known-good production build → **Promote to
Production**. The CLI equivalent is `vercel rollback <deployment-url>`.
Rolling back code does not roll back schema or vectors; `app.seed` migrations
are additive (`ADD COLUMN IF NOT EXISTS`), so an older build can still read
the database.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `VERCEL_TOKEN is empty` | Added as a **variable** instead of a **secret**, or missing on the `production` environment. |
| `VERCEL_TOKEN contains whitespace` | Re-paste the token without a trailing newline. |
| `vercel whoami failed` | Token expired or lacks access to `team_OuVuWFb4CX4GlaWa2YbnNyAC`. |
| `No module named 'pydantic_core._pydantic_core'` | Python versions drifted. Align `.python-version`, `UV_PYTHON`, and the project setting at 3.14, then redeploy. |
| Function boots but every request 500s | `PYTHONPATH=backend` missing, or `JWT_SECRET`/`DATABASE_URL` unset. Check the function logs. |
| Browser blocks requests (CORS) | `ALLOWED_ORIGINS` must be the exact frontend origin, no trailing slash. |
| `/health` 503 | Postgres unreachable — check the Neon connection string and whether the branch is suspended. |
| Answers say "I don't know" | Qdrant empty or wrong collection. Run `app.ingest` with the same `EMBEDDING_MODEL` used in production. |
| Frontend calls the wrong API | `NEXT_PUBLIC_API_URL` is baked in at build time; change it and redeploy. |

---

## Related documents

- [`README.md`](README.md) — setup, API reference, architecture.
- [`plan.md`](plan.md) — build status and known rough edges.
- [`PRODUCTION-HARDENING.MD`](PRODUCTION-HARDENING.MD) — logging, health,
  rate limiting, request limits.
- `.github/workflows/deploy.yml` — the authoritative list of secrets, env
  vars, and steps.
