from app import rag_chain


def test_generate_answer_delegates_to_core(monkeypatch):
    def fake_ask(question):
        assert question == "any question"
        return {
            "answer": "core answer",
            "sources": [{"source": "hospital_policy.pdf", "page": 3}],
            "documents": [],
        }

    monkeypatch.setattr(rag_chain, "ask", fake_ask)

    assert (
        rag_chain.generate_answer("any question")
        == "core answer\n\nSources:\n- hospital_policy.pdf — page 3"
    )


def test_generate_answer_without_sources(monkeypatch):
    monkeypatch.setattr(
        rag_chain,
        "ask",
        lambda question: {"answer": "core answer", "sources": [], "documents": []},
    )

    assert rag_chain.generate_answer("any question") == "core answer"
