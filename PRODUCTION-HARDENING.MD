# Production Hardening

## Overview

This document describes the reliability, observability, and basic security improvements implemented in the Agentic RAG backend.

The backend uses FastAPI, LangGraph, Qdrant, PostgreSQL, and an LLM provider. These improvements help make the API more reliable and easier to monitor during development and deployment.

## 1. Logging and Observability

Application logging records useful information about API requests, including:

- User and conversation identifiers, where available
- Selected agent route
- Request processing time
- Error information

Example log:

```text
ask user=4 conversation=56 route=database elapsed_ms=9235 error=None
```

This helps identify slow requests, understand routing decisions, and investigate errors without relying only on terminal output.

## 2. Health Check

The backend exposes a health endpoint:

```http
GET /health
```

Example response:

```json
{
  "status": "ok",
  "database": "up"
}
```

The probe runs a trivial Postgres query. It returns `200` when the database
answers and `503` with `{"status": "degraded", "database": "down"}` when it
does not, so an orchestrator can tell "serving" from "up but broken". It does
not touch Qdrant or the LLM provider.

## 3. Rate Limiting

Rate limiting restricts the number of requests a client can make within a time window.

The current configuration uses an in-memory rate limiter with a default limit of 60 requests per minute per client IP. The limit can be configured using `RATE_LIMIT_PER_MINUTE`.

Requests that exceed the limit receive HTTP `429 Too Many Requests`. The `/health` endpoint is exempt.

**Limitation:** Because the limiter stores its state in memory, limits are not shared across multiple backend instances, and the state resets when the process restarts.

## 4. Global Exception Handling

A global exception handler provides a consistent response when an unexpected server error occurs.

- Unexpected exceptions are logged for debugging.
- Clients receive a generic HTTP 500 response.
- A request identifier helps correlate an error response with server logs.

Internal exception details should not be exposed to clients.

## 5. Database Connection Resilience

SQLAlchemy connection pooling is configured with `pool_pre_ping=True`.

This checks whether a pooled database connection is still valid before using it, helping reduce errors caused by stale connections.

## 6. LLM Timeout and Retry Configuration

The LLM client uses `LLM_TIMEOUT_SECONDS` (default **60**) per attempt and
`LLM_MAX_RETRIES` (default **2**) extra attempts for transient 429/5xx
responses and dropped connections, on both Groq and Gemini.

These settings prevent a stalled call from pinning a worker and let a dropped
packet retry instead of failing the turn. Failure paths are covered by
`tests/test_hardening.py`.

## 7. Request-Size Protection

`MAX_REQUEST_BODY_BYTES` (default 1 MiB) is enforced twice: the declared
`Content-Length` rejects the request before a byte is read, and a wrapped
`receive()` counts bytes as they arrive, so chunked bodies and false headers
are caught too. Both return `413`. The middleware is registered innermost, so
the short-circuited response still carries CORS headers a browser can read.

**Limitation:** This is application-level only. A reverse proxy or platform
edge should still cap request bodies before traffic reaches the app.

## 8. Validation Summary

| Feature | Status |
|---|---|
| Backend startup | Tested |
| `/health` endpoint | Tested |
| Rate limiting and HTTP 429 | Tested |
| RAG and database-routed requests | Tested |
| Database connection pre-ping | Configured |
| Global exception handling | Implemented; covered by `tests/test_hardening.py` |
| LLM timeout and retries | Configured; failure paths covered by `tests/test_hardening.py` |
| Request-size protection | Declared and streamed bytes; covered by `tests/test_hardening.py` |
| Per-instance rate limiting on Vercel | Known limitation — counters are per warm instance |

## Conclusion

These improvements strengthen the backend's basic reliability, observability, and request protection, and they are deployed on Vercel. Remaining production work is persistent rate-limit storage (Redis) for multiple instances, token revocation/refresh, and security headers.
