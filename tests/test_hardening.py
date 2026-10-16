"""Verification for the Item 6 hardening: LLM call budget and body-size limits.

Nothing here calls a real provider. The timeout test points the client at a
local socket that accepts and never answers — the exact failure the timeout
exists to bound — and the retry test uses an in-memory transport that returns
500. The live API is not involved in either.
"""

import asyncio
import socket
import threading
import time

import groq
import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import api, llm
from app.api import (
    MAX_REQUEST_BODY_BYTES,
    BodySizeLimitMiddleware,
    RequestBodyTooLarge,
    _send_json,
)
from app.db import get_session


# --------------------------------------------------------------------------
# LLM timeout / retry
# --------------------------------------------------------------------------


def test_get_llm_passes_timeout_and_retries_to_gemini(monkeypatch):
    captured = {}

    class FakeGemini:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "ChatGoogleGenerativeAI", FakeGemini)
    monkeypatch.setattr(llm, "GOOGLE_API_KEY", "key")

    llm.get_llm()

    assert captured["timeout"] == llm.LLM_TIMEOUT_SECONDS
    assert captured["max_retries"] == llm.LLM_MAX_RETRIES


def test_get_llm_passes_timeout_and_retries_to_groq(monkeypatch):
    captured = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "ChatGroq", FakeGroq)
    monkeypatch.setattr(llm, "GOOGLE_API_KEY", None)

    llm.get_llm()

    assert captured["request_timeout"] == llm.LLM_TIMEOUT_SECONDS
    assert captured["max_retries"] == llm.LLM_MAX_RETRIES


class _HungProvider:
    """Local TCP server that accepts connections and never answers."""

    def __init__(self):
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self.accepted = 0
        self._closed = False
        self._conns = []

    def __enter__(self):
        def accept_loop():
            while not self._closed:
                try:
                    conn, _ = self._sock.accept()
                except OSError:
                    return
                self.accepted += 1
                self._conns.append(conn)

        self._thread = threading.Thread(target=accept_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass
        self._thread.join(timeout=2)


def test_hung_provider_call_is_bounded_by_the_timeout():
    """A provider that accepts and goes quiet must not pin the worker."""
    with _HungProvider() as provider:
        chat = ChatGroq(
            model="llama-3.1-8b-instant",
            groq_api_key="test-key",
            groq_api_base=f"http://127.0.0.1:{provider.port}/",
            request_timeout=1.0,
            max_retries=0,
        )

        started = time.monotonic()
        with pytest.raises((groq.APITimeoutError, groq.APIConnectionError)):
            chat.invoke([HumanMessage(content="hi")])
        elapsed = time.monotonic() - started

    assert elapsed < 10, f"call ran {elapsed:.1f}s with a 1s timeout"
    assert provider.accepted >= 1


def test_transient_provider_errors_are_retried_a_bounded_number_of_times():
    """A 5xx is retried, and the retries stop at max_retries."""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(500, json={"error": {"message": "boom"}})

    transport = httpx.MockTransport(handler)
    completions = groq.Groq(
        api_key="test-key",
        max_retries=2,
        http_client=httpx.Client(transport=transport),
    ).chat.completions
    chat = ChatGroq(model="llama-3.1-8b-instant", client=completions)

    with pytest.raises(groq.APIStatusError):
        chat.invoke([HumanMessage(content="hi")])

    assert len(attempts) == 3, f"expected 1 attempt + 2 retries, got {len(attempts)}"


# --------------------------------------------------------------------------
# Request-size limit
# --------------------------------------------------------------------------


@pytest.fixture()
def client():
    """In-memory SQLite session override; never reaches live Neon."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def test_session():
        with Session(engine) as session:
            yield session

    api.app.dependency_overrides[get_session] = test_session
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_declared_oversized_body_is_refused_without_reading_it(client):
    response = client.post("/ask", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1))

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large."}


def test_streamed_body_over_the_limit_is_refused(client):
    """No trustworthy Content-Length: the actual bytes decide."""
    chunk = b"x" * (128 * 1024)
    count = MAX_REQUEST_BODY_BYTES // (128 * 1024) + 1

    response = client.post("/ask", content=(chunk for _ in range(count)))

    assert response.status_code == 413


def test_stream_guard_counts_actual_bytes_when_content_length_lies():
    """Header claims 5 bytes, 1.2 MB arrive — still a 413.

    Drives the middleware directly so the streaming path is covered
    regardless of what any HTTP client chooses to declare.
    """
    sent = []

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        # Stands in for FastAPI plus the registered RequestBodyTooLarge handler.
        try:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] == "http.request" and not message.get("more_body"):
                    break
        except RequestBodyTooLarge:
            await _send_json(send, 413, {"detail": "Request body too large."})
            return
        await _send_json(send, 200, {"detail": "ok"})

    chunk = b"x" * (600 * 1024)

    async def body_events():
        yield {"type": "http.request", "body": chunk, "more_body": True}
        yield {"type": "http.request", "body": chunk, "more_body": True}
        yield {"type": "http.request", "body": b"", "more_body": False}

    events = body_events()

    async def receive():
        return await events.__anext__()

    scope = {"type": "http", "headers": [(b"content-length", b"5")]}
    middleware = BodySizeLimitMiddleware(downstream, max_bytes=MAX_REQUEST_BODY_BYTES)

    asyncio.run(middleware(scope, receive, send))

    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses == [413]


def test_body_within_the_limit_is_still_processed(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "run_agent",
        lambda question, u=None, history=None, conversation_id=None: {
            "question": question,
            "route": "rag",
            "answer": "Visiting hours are 10am to 8pm.",
            "sources": [],
            "documents": [],
            "error": None,
            "user_id": None,
            "user_role": None,
        },
    )

    response = client.post("/ask", json={"question": "What are visiting hours?"})

    assert response.status_code == 200


def test_413_reaches_the_browser_with_cors_headers(client):
    """The size limit sits inside CORS, so its 413 is readable cross-origin."""
    response = client.post(
        "/ask",
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_health_is_unaffected_by_the_size_limit(client):
    assert client.get("/health").status_code == 200
