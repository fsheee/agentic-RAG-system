"""Conversation memory on POST /ask.

Runs against a real in-memory SQLite database so the actual crud helpers
are exercised, with real signed JWTs so ownership is enforced the way it
is in production.

The rules under test throughout: a conversation belongs to exactly one
user, anonymous callers get no memory at all, and history replayed into
the prompt is treated as untrusted data.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import api
from app.auth import create_access_token
from app.crud import (
    MAX_MESSAGE_CHARS,
    append_message,
    create_conversation,
    get_recent_messages,
)
from app.db import get_session
from app.schema import Conversation, Message, Role, User


def _user(name, email, role=Role.patient):
    return User(name=name, email=email, password_hash="x", role=role)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def test_session():
        with Session(engine) as session:
            yield session

    # expire_on_commit=False keeps these usable to mint tokens after the
    # seeding session closes.
    with Session(engine, expire_on_commit=False) as session:
        alice = _user("Alice", "alice@example.com")
        bob = _user("Bob", "bob@example.com")
        session.add(alice)
        session.add(bob)
        session.commit()
        users = {"alice": alice, "bob": bob}

    api.app.dependency_overrides[get_session] = test_session
    yield TestClient(api.app), users, engine
    api.app.dependency_overrides.clear()


def _auth(user: User) -> dict:
    token = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


def _stub_agent(monkeypatch, answer="Visiting hours are 10am to 8pm."):
    """Stub the agent and record what it was called with."""
    calls = []

    def fake(question, user=None, history=None, conversation_id=None):
        calls.append(
            {
                "question": question,
                "user": user,
                "history": history,
                "conversation_id": conversation_id,
            }
        )
        return {
            "question": question,
            "route": "rag",
            "answer": answer,
            "sources": [],
            "documents": [],
            "error": None,
            "user_id": user.id if user else None,
            "user_role": user.role.value if user else None,
            "history": history,
            "conversation_id": conversation_id,
        }

    monkeypatch.setattr(api, "run_agent", fake)
    return calls


def _count(engine, model) -> int:
    with Session(engine) as session:
        return len(session.exec(select(model)).all())


# --------------------------------------------------------------------------
# Anonymous callers get no memory
# --------------------------------------------------------------------------


def test_anonymous_ask_persists_nothing(ctx, monkeypatch):
    http, _users, engine = ctx
    _stub_agent(monkeypatch)

    response = http.post("/ask", json={"question": "What are visiting hours?"})

    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    assert _count(engine, Conversation) == 0
    assert _count(engine, Message) == 0


def test_anonymous_ask_with_a_conversation_id_is_rejected(ctx, monkeypatch):
    """Without an identity there is nothing to scope history to, so this
    must not silently load or write someone else's conversation."""
    http, _users, engine = ctx
    calls = _stub_agent(monkeypatch)

    response = http.post(
        "/ask", json={"question": "What are visiting hours?", "conversation_id": 1}
    )

    assert response.status_code == 400
    assert calls == []  # the agent is never reached
    assert _count(engine, Message) == 0


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_first_authenticated_ask_creates_a_conversation(ctx, monkeypatch):
    http, users, engine = ctx
    _stub_agent(monkeypatch)

    response = http.post(
        "/ask",
        json={"question": "What are visiting hours?"},
        headers=_auth(users["alice"]),
    )

    assert response.status_code == 201 or response.status_code == 200
    conversation_id = response.json()["conversation_id"]
    assert conversation_id is not None

    with Session(engine) as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.user_id == users["alice"].id
        assert conversation.title == "What are visiting hours?"

        messages = session.exec(
            select(Message).where(Message.conversation_id == conversation_id)
        ).all()
        assert [(m.role, m.content) for m in messages] == [
            ("user", "What are visiting hours?"),
            ("assistant", "Visiting hours are 10am to 8pm."),
        ]


def test_follow_up_continues_the_same_conversation(ctx, monkeypatch):
    http, users, engine = ctx
    calls = _stub_agent(monkeypatch)
    headers = _auth(users["alice"])

    first = http.post(
        "/ask", json={"question": "What are visiting hours?"}, headers=headers
    )
    conversation_id = first.json()["conversation_id"]

    second = http.post(
        "/ask",
        json={"question": "And on weekends?", "conversation_id": conversation_id},
        headers=headers,
    )

    assert second.json()["conversation_id"] == conversation_id
    assert _count(engine, Conversation) == 1
    assert _count(engine, Message) == 4  # two turns

    # The second call saw the first turn as history.
    assert calls[0]["history"] == []
    assert [m["role"] for m in calls[1]["history"]] == ["user", "assistant"]
    assert calls[1]["history"][0]["content"] == "What are visiting hours?"


def test_history_is_plain_dicts_not_orm_objects(ctx, monkeypatch):
    """AgentState must stay serializable; core never sees a Message row."""
    http, users, engine = ctx
    calls = _stub_agent(monkeypatch)
    headers = _auth(users["alice"])

    first = http.post("/ask", json={"question": "One?"}, headers=headers)
    http.post(
        "/ask",
        json={"question": "Two?", "conversation_id": first.json()["conversation_id"]},
        headers=headers,
    )

    for message in calls[1]["history"]:
        assert type(message) is dict
        assert set(message) == {"role", "content"}


def test_unknown_conversation_id_is_404(ctx, monkeypatch):
    http, users, _engine = ctx
    calls = _stub_agent(monkeypatch)

    response = http.post(
        "/ask",
        json={"question": "Hello?", "conversation_id": 9999},
        headers=_auth(users["alice"]),
    )

    assert response.status_code == 404
    assert calls == []


# --------------------------------------------------------------------------
# Ownership isolation
# --------------------------------------------------------------------------


def test_user_cannot_continue_another_users_conversation(ctx, monkeypatch):
    """The central rule: a conversation belongs to exactly one user."""
    http, users, engine = ctx
    calls = _stub_agent(monkeypatch)

    alice = http.post(
        "/ask",
        json={"question": "What are visiting hours?"},
        headers=_auth(users["alice"]),
    )
    conversation_id = alice.json()["conversation_id"]

    stolen = http.post(
        "/ask",
        json={"question": "What did she ask?", "conversation_id": conversation_id},
        headers=_auth(users["bob"]),
    )

    # 404, not 403: Bob learns nothing about whether the row exists.
    assert stolen.status_code == 404
    assert calls == [calls[0]]  # Bob's turn never reached the agent

    # Alice's conversation was neither read nor written by Bob.
    with Session(engine) as session:
        messages = session.exec(
            select(Message).where(Message.conversation_id == conversation_id)
        ).all()
        assert len(messages) == 2


def test_each_user_gets_their_own_conversation(ctx, monkeypatch):
    http, users, engine = ctx
    _stub_agent(monkeypatch)

    alice = http.post(
        "/ask", json={"question": "Alice asks"}, headers=_auth(users["alice"])
    )
    bob = http.post("/ask", json={"question": "Bob asks"}, headers=_auth(users["bob"]))

    assert alice.json()["conversation_id"] != bob.json()["conversation_id"]
    assert _count(engine, Conversation) == 2


# --------------------------------------------------------------------------
# Windowing
# --------------------------------------------------------------------------


def test_history_is_windowed_to_the_most_recent_messages(ctx, monkeypatch):
    http, users, engine = ctx
    calls = _stub_agent(monkeypatch)

    with Session(engine) as session:
        conversation = create_conversation(session, users["alice"].id, "seeded")
        conversation_id = conversation.id
        for index in range(15):
            append_message(session, conversation_id, "user", f"message {index}")

    http.post(
        "/ask",
        json={"question": "Latest?", "conversation_id": conversation_id},
        headers=_auth(users["alice"]),
    )

    history = calls[0]["history"]
    assert len(history) == 10  # crud.HISTORY_LIMIT
    # Oldest first, and it is the *most recent* ten that survive.
    assert history[0]["content"] == "message 5"
    assert history[-1]["content"] == "message 14"


# --------------------------------------------------------------------------
# crud helpers
# --------------------------------------------------------------------------


def test_get_recent_messages_is_chronological(ctx):
    _http, users, engine = ctx

    with Session(engine) as session:
        conversation = create_conversation(session, users["alice"].id, "t")
        for index in range(5):
            append_message(session, conversation.id, "user", f"m{index}")

        recent = get_recent_messages(session, conversation.id, limit=3)

    assert [m.content for m in recent] == ["m2", "m3", "m4"]


def test_append_message_truncates_and_bumps_updated_at(ctx):
    _http, users, engine = ctx

    with Session(engine) as session:
        conversation = create_conversation(session, users["alice"].id, "t")
        before = conversation.updated_at

        message = append_message(session, conversation.id, "user", "x" * 20000)

        assert len(message.content) == MAX_MESSAGE_CHARS
        session.refresh(conversation)
        assert conversation.updated_at >= before


def test_conversation_lookup_filters_by_owner(ctx):
    from app.crud import get_conversation_for_user

    _http, users, engine = ctx

    with Session(engine) as session:
        conversation = create_conversation(session, users["alice"].id, "t")

        assert (
            get_conversation_for_user(session, conversation.id, users["alice"].id)
            is not None
        )
        assert (
            get_conversation_for_user(session, conversation.id, users["bob"].id) is None
        )
