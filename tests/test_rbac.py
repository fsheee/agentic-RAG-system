"""Role-based access control inside the agent graph.

Role checks happen in Python (graph nodes) and in the Qdrant retrieval
filter (app/access.py) — never in the LLM.

Two separate policies are covered here:
- the RAG route is scoped to the document tiers a role may read, where
  anonymous means public documents only;
- appointment data is restricted to patients (their own) and admins, and
  an anonymous caller is refused outright.
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


def _record_rag(monkeypatch, answer="Visiting hours are 10am to 8pm."):
    """Stub the RAG tool, recording the access tiers it was called with."""
    calls = []

    def fake(question, access=None):
        calls.append(access)
        return {"answer": answer, "sources": [], "documents": []}

    monkeypatch.setattr(graph.rag_tool, "search_knowledge_base", fake)

    return calls


def _record_action(monkeypatch):
    """Stub the booking action tool, recording whether it was reached."""
    calls = []

    def fake(question, user=None):
        calls.append((question, user))
        return "Appointment #3 has been cancelled."

    monkeypatch.setattr(graph.booking_tool, "handle_appointment_action", fake)

    return calls


# --- RAG access tiers -------------------------------------------------


def test_anonymous_rag_call_is_scoped_to_public_documents(monkeypatch):
    """No token must mean the most restricted tier, not the widest."""
    _patch(monkeypatch, "rag")
    calls = _record_rag(monkeypatch)

    state = run_agent("What are the visiting hours?")

    assert calls == [{"public"}]
    assert state["answer"] == "Visiting hours are 10am to 8pm."


def test_patient_rag_call_is_scoped_to_public_documents(monkeypatch):
    _patch(monkeypatch, "rag")
    calls = _record_rag(monkeypatch)

    state = run_agent("What are the visiting hours?", user=_user(Role.patient))

    assert calls == [{"public"}]
    assert state["answer"] == "Visiting hours are 10am to 8pm."


def test_staff_rag_call_is_scoped_to_both_tiers(monkeypatch):
    _patch(monkeypatch, "rag")
    calls = _record_rag(monkeypatch)

    run_agent("What is the probation period?", user=_user(Role.employee))

    assert calls == [{"public", "staff"}]


def test_hr_role_reads_the_staff_tier(monkeypatch):
    _patch(monkeypatch, "rag")
    calls = _record_rag(monkeypatch)

    run_agent("What is the probation period?", user=_user(Role.hr))

    assert calls == [{"public", "staff"}]


def test_rag_route_no_longer_refuses_any_role(monkeypatch):
    """The old blanket staff-only refusal is gone: every role gets an answer."""
    _patch(monkeypatch, "rag")
    _record_rag(monkeypatch)

    for role in Role:
        state = run_agent("What are the visiting hours?", user=_user(role))

        assert state["answer"] == "Visiting hours are 10am to 8pm.", role
        assert "staff only" not in state["answer"], role


# --- Appointment data -------------------------------------------------


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


def test_appointment_listing_denied_for_anonymous(monkeypatch):
    _patch(monkeypatch, "database")
    called = []
    monkeypatch.setattr(
        graph.booking_tool, "list_appointments", lambda u=None: called.append(u)
    )

    state = run_agent("Show my appointments")

    assert "sign in" in state["answer"].lower()
    assert called == []


def test_booking_route_denied_for_anonymous(monkeypatch):
    _patch(monkeypatch, "booking")
    called = []
    monkeypatch.setattr(
        graph.booking_tool, "run_booking", lambda q, u=None: called.append(q)
    )

    state = run_agent("Book an appointment with Dr. Sarah tomorrow at 10am")

    assert "sign in" in state["answer"].lower()
    assert called == []


def test_anonymous_cancel_never_reaches_the_booking_tool(monkeypatch):
    """The booking tools treat a missing user as the seeded demo patient,
    so an anonymous cancel must be refused before the tool is called —
    on the database route too, where the router sometimes sends it."""
    for route in ("booking", "database"):
        _patch(monkeypatch, route)
        calls = _record_action(monkeypatch)

        state = run_agent("Cancel appointment 3")

        assert calls == [], route
        assert "sign in" in state["answer"].lower(), route


def test_doctor_lookup_still_answers_anonymous_callers(monkeypatch):
    """Doctor lists are public hospital information, not appointment data."""
    _patch(monkeypatch, "database")
    monkeypatch.setattr(
        graph.db_tool,
        "list_doctors",
        lambda: [{"id": 1, "name": "Dr. A", "specialization": "Cardiology"}],
    )

    state = run_agent("Which doctors are available?")

    assert "Dr. A" in state["answer"]
