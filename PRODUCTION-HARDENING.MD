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
  "status": "ok"
}
```

This is a basic liveness check that confirms the API is responding. It does not guarantee that PostgreSQL, Qdrant, or the LLM provider is available.

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

The LLM client is configured with a request timeout of 30 seconds and up to two retries.

These settings help prevent requests from waiting indefinitely and allow certain transient failures to be retried.

Actual timeout and retry behavior should also be tested under simulated provider failures.

## 7. Request-Size Protection

The API checks the declared `Content-Length` header and rejects requests larger than 1 MB with HTTP `413 Payload Too Large`.

This is a basic safeguard against oversized requests.

**Limitation:** Header-based validation alone is not sufficient to enforce a strict body-size limit for every request. Production deployment should also enforce request-size limits at the ASGI server or reverse proxy layer.

## 8. Validation Summary

| Feature | Status |
|---|---|
| Backend startup | Tested |
| `/health` endpoint | Tested |
| Rate limiting and HTTP 429 | Tested |
| RAG and database-routed requests | Tested |
| Database connection pre-ping | Configured |
| Global exception handling | Implemented; failure-path testing pending |
| LLM timeout and retries | Configured; failure-path testing pending |
| Request-size protection | Basic check implemented; additional testing pending |

## Conclusion

These improvements strengthen the backend's basic reliability, observability, and request protection. They provide a foundation for deployment while leaving clear next steps for production readiness, including failure-path testing, persistent rate-limit storage for multiple instances, and stronger request-size enforcement.