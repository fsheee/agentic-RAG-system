import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select
from starlette.requests import Request

from app.agent import run_agent
from app.appointment_routes import router as appointment_router
from app.auth_routes import get_optional_user, router as auth_router
from app.crud import (
    append_message,
    create_conversation,
    get_conversation_for_user,
    get_recent_messages,
)
from app.db import get_session
from app.schema import User

# INFO-level request summaries by default; uvicorn config may raise it.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
logger = logging.getLogger("app.api")


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional so existing clients keep working. Supplying one continues
    # that conversation; the caller must own it.
    #
    # ge=1 rejects 0 and negatives as malformed input (422). Without it a
    # `conversation_id: 0` reaches the anonymous check below, where `0 is
    # not None` is true and the caller is told "Sign in to use conversation
    # history" — which reads like a permissions problem rather than a bad
    # id. Real ids start at 1, so anything lower is a request error.
    conversation_id: int | None = Field(default=None, ge=1)


class Source(BaseModel):
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    # None when the caller is anonymous (no memory is kept).
    conversation_id: int | None = None


app = FastAPI(title="Agentic RAG API")

# Real origins only: browsers reject a wildcard combined with
# allow_credentials, and the frontend authenticates with a bearer token
# sent from an explicit origin. Comma-separated, no spaces needed.
# e.g. ALLOWED_ORIGINS=http://localhost:3000,https://app.example.com
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Responses are text-heavy (RAG answers, doctor lists).
app.add_middleware(GZipMiddleware, minimum_size=1000)


class SlidingWindowRateLimiter:
    """In-process sliding-window limiter, one bucket per key (client IP).

    In-memory by design: a single-process deployment needs no Redis, and
    the lock keeps the deque bookkeeping correct under concurrent
    requests. Counters reset on restart — acceptable for abuse damping,
    not for quota accounting.
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True


RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
rate_limiter = SlidingWindowRateLimiter(RATE_LIMIT_PER_MINUTE)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    """429 the caller once their window is full.

    /health is exempt: a liveness probe that gets throttled looks like an
    outage to the orchestrator.
    """
    if request.url.path == "/health":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        logger.warning(
            "rate limit exceeded client=%s path=%s", client_ip, request.url.path
        )
        return JSONResponse(
            {"detail": "Too many requests, slow down."}, status_code=429
        )

    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the traceback, return a stable 500 body.

    Expected failures (guardrails, RBAC, not-found) are raised as
    HTTPException and never reach here; this only catches bugs. The
    request id ties the client's error to the logged traceback.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    logger.exception(
        "unhandled error request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        {"detail": "Internal server error.", "request_id": request_id},
        status_code=500,
    )

app.include_router(auth_router)
app.include_router(appointment_router)


@app.get("/health")
def health(session: Session = Depends(get_session)) -> JSONResponse:
    """Liveness probe: the database must answer a trivial query.

    200 with {"status": "ok"} when up; 503 with {"status": "degraded"}
    when the dependency check fails, so orchestrators and uptime checks
    can tell "process is serving" from "process is up but broken".
    """
    database = "up"
    try:
        session.exec(select(func.count()).select_from(User)).one()
    except Exception:
        logger.exception("health check: database unreachable")
        database = "down"

    return JSONResponse(
        {"status": "ok" if database == "up" else "degraded", "database": database},
        status_code=status.HTTP_200_OK if database == "up" else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.post("/ask", response_model=AskResponse)
def ask_question(
    request: AskRequest,
    user: User | None = Depends(get_optional_user),
    session: Session = Depends(get_session),
) -> AskResponse:
    """
    Agent endpoint: guardrail -> router -> RAG/database/general -> validate.
    The RAG route itself lives in core.ask() via the agent's rag tool.

    Authentication is optional. Anonymous callers get public hospital
    information only; a valid token widens access to what the caller's
    role may read. Identity and role come from the JWT, never the request
    body, and are enforced in the graph nodes and the Qdrant retrieval
    filter — never by the LLM.

    Conversation memory is for authenticated callers only. A conversation
    must have an owner for "a user reads only their own conversations" to
    mean anything, so anonymous callers get no history and nothing is
    persisted for them.
    """
    conversation = None

    if user is None:
        if request.conversation_id is not None:
            # Never load or write history without an identity to scope it to.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Sign in to use conversation history.",
            )
    elif request.conversation_id is None:
        conversation = create_conversation(session, user.id, title=request.question)
    else:
        # Ownership-checked: another user's id resolves to None. 404 rather
        # than 403 so the response does not confirm that the row exists.
        conversation = get_conversation_for_user(
            session, request.conversation_id, user.id
        )
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    history = None
    if conversation is not None:
        # Windowed in the query; core.format_history caps the rendered size.
        history = [
            {"role": message.role, "content": message.content}
            for message in get_recent_messages(session, conversation.id)
        ]

    started = time.perf_counter()
    state = run_agent(
        request.question,
        user,
        history=history,
        conversation_id=conversation.id if conversation else None,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    logger.info(
        "ask user=%s conversation=%s route=%s elapsed_ms=%.0f error=%s",
        user.id if user else None,
        conversation.id if conversation else None,
        state.get("route"),
        elapsed_ms,
        state.get("error"),
    )

    if conversation is not None:
        append_message(session, conversation.id, "user", request.question)
        append_message(session, conversation.id, "assistant", state["answer"])

    return AskResponse(
        answer=state["answer"],
        sources=[Source(**s) for s in state["sources"]],
        conversation_id=conversation.id if conversation else None,
    )
