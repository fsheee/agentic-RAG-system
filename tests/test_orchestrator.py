from app.agent import orchestrator


class FakeResponse:
    def __init__(self, content):
        self.content = content


def make_llm(content):
    return type("FakeLLM", (), {"invoke": lambda self, p: FakeResponse(content)})()


def test_routes_to_rag(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm", lambda: make_llm("rag"))

    assert orchestrator.orchestrator({"question": "What are the visiting hours?"}) == {"route": "rag"}


def test_routes_to_doctor(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm", lambda: make_llm("doctor"))

    assert orchestrator.orchestrator({"question": "Which doctors are available?"}) == {"route": "doctor"}


def test_routes_to_booking(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm", lambda: make_llm("booking"))

    assert orchestrator.orchestrator({"question": "I want to book an appointment."}) == {"route": "booking"}


def test_falls_back_to_rag_on_unknown_route(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm", lambda: make_llm("surgery"))

    assert orchestrator.orchestrator({"question": "anything"}) == {"route": "rag"}


def test_strips_and_lowercases_route(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm", lambda: make_llm("  RAG\n"))

    assert orchestrator.orchestrator({"question": "anything"}) == {"route": "rag"}


def test_joins_gemini_list_content(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "get_llm",
        lambda: make_llm([{"text": "book"}, {"text": "ing"}]),
    )

    assert orchestrator.orchestrator({"question": "anything"}) == {"route": "booking"}
