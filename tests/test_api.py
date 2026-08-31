from fastapi.testclient import TestClient

from app import api


def _client(monkeypatch, result):
    monkeypatch.setattr(api.core, "ask", lambda question: result)
    return TestClient(api.app)


def test_ask_returns_answer_and_sources(monkeypatch):
    client = _client(
        monkeypatch,
        {
            "answer": "Visiting hours are 10am to 8pm.",
            "sources": [{"source": "hospital_policy.pdf", "page": 3}],
            "documents": [],
        },
    )

    response = client.post("/ask", json={"question": "What are visiting hours?"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Visiting hours are 10am to 8pm.",
        "sources": [{"source": "hospital_policy.pdf", "page": 3}],
    }


def test_ask_forwards_question_to_core(monkeypatch):
    seen = []

    def fake_ask(question):
        seen.append(question)
        return {"answer": "ok", "sources": [], "documents": []}

    monkeypatch.setattr(api.core, "ask", fake_ask)
    client = TestClient(api.app)

    client.post("/ask", json={"question": "What is the hospital policy on visitors?"})

    assert seen == ["What is the hospital policy on visitors?"]


def test_ask_rejects_empty_question(monkeypatch):
    monkeypatch.setattr(
        api.core, "ask", lambda question: {"answer": "x", "sources": [], "documents": []}
    )
    client = TestClient(api.app)

    response = client.post("/ask", json={"question": ""})

    assert response.status_code == 422


def test_ask_without_question_is_unprocessable(monkeypatch):
    monkeypatch.setattr(
        api.core, "ask", lambda question: {"answer": "x", "sources": [], "documents": []}
    )
    client = TestClient(api.app)

    response = client.post("/ask", json={})

    assert response.status_code == 422
