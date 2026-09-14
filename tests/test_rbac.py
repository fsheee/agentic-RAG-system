"""Role-based access control inside the agent graph.

Role checks happen in Python (graph nodes) — never in the LLM. The user
context comes from the JWT via /ask; None keeps the legacy
unauthenticated behavior used by other tests.
"""

from app.agent import graph, run_agent
from app.schema import Role, User


def _user(role, user_id=1):
    return User(
        id=user_id,
        name="Test User",
        email="user@example.com",
        password_hash="x",
        role=role,
        is_active=True,
    )


def _patch(monkeypatch, route):
    monkeypatch.setattr(graph, "route_question", lambda question: route)


def test_rag_route_allowed_for_employee(monkeypatch):
    _patch(monkeypatch, "rag")
    monkeypatch.setattr(
        graph.rag_tool,
        "search_knowledge_base",
        lambda question: {
            "answer": "Visiting hours are 10am to 8pm.",
            "sources": [],
            "documents": [],
        },
    )

    state = run_agent("What are the visiting hours?", user=_user(Role.employee))

    assert state["answer"] == "Visiting hours are 10am to 8pm."


def test_rag_route_denied_for_patient(monkeypatch):
    _patch(monkeypatch, "rag")

    state = run_agent("What are the visiting hours?", user=_user(Role.patient))

    assert "staff only" in state["answer"]
    assert state["sources"] == []


def test_booking_route_denied_for_employee(monkeypatch):
    _patch(monkeypatch, "booking")
    called = []
    monkeypatch.setattr(
        graph.booking_tool, "run_booking", lambda q, u=None: called.append(q)
    )

    state = run_agent(
        "Book an appointment with Dr. Sarah tomorrow at 10am",
        user=_user(Role.employee),
    )

    assert "patients" in state["answer"]
    assert called == []  # the tool is never reached


def test_appointment_listing_denied_for_employee(monkeypatch):
    _patch(monkeypatch, "database")
    called = []
    monkeypatch.setattr(
        graph.booking_tool, "list_appointments", lambda u=None: called.append(u)
    )

    state = run_agent("Show my appointments", user=_user(Role.employee))

    assert "patients" in state["answer"]
    assert called == []


def test_unauthenticated_run_keeps_legacy_behavior(monkeypatch):
    _patch(monkeypatch, "rag")
    monkeypatch.setattr(
        graph.rag_tool,
        "search_knowledge_base",
        lambda question: {
            "answer": "Visiting hours are 10am to 8pm.",
            "sources": [],
            "documents": [],
        },
    )

    state = run_agent("What are the visiting hours?")

    assert state["answer"] == "Visiting hours are 10am to 8pm."
