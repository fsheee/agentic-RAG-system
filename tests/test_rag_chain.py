from langchain_core.documents import Document

from app import rag_chain


class FakeResponse:
    def __init__(self, content):
        self.content = content


def test_returns_string_content(monkeypatch):
    monkeypatch.setattr(
        rag_chain,
        "retrieve_documents",
        lambda query: [Document(page_content="context one")],
    )
    monkeypatch.setattr(
        rag_chain,
        "get_llm",
        lambda: type("FakeLLM", (), {"invoke": lambda self, p: FakeResponse("plain answer")})(),
    )

    assert rag_chain.generate_answer("any question") == "plain answer"


def test_joins_gemini_list_content(monkeypatch):
    monkeypatch.setattr(
        rag_chain,
        "retrieve_documents",
        lambda query: [Document(page_content="context one")],
    )
    monkeypatch.setattr(
        rag_chain,
        "get_llm",
        lambda: type(
            "FakeLLM",
            (),
            {
                "invoke": lambda self, p: FakeResponse(
                    [{"text": "Gemini "}, {"text": "answer"}]
                )
            },
        )(),
    )

    assert rag_chain.generate_answer("any question") == "Gemini answer"


def test_builds_context_from_retrieved_documents(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        rag_chain,
        "retrieve_documents",
        lambda query: [
            Document(page_content="chunk one"),
            Document(page_content="chunk two"),
        ],
    )
    monkeypatch.setattr(
        rag_chain,
        "get_llm",
        lambda: type(
            "FakeLLM",
            (),
            {
                "invoke": lambda self, p: (
                    captured.update({"prompt": p}),
                    FakeResponse("done"),
                )[1]
            },
        )(),
    )

    rag_chain.generate_answer("my question")

    rendered = captured["prompt"].to_string()
    assert "chunk one" in rendered
    assert "chunk two" in rendered
    assert "my question" in rendered