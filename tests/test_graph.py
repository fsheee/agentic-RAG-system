from langchain_core.documents import Document

from app.agent import graph


class FakeResponse:
    def __init__(self, content):
        self.content = content


def test_graph_retrieves_and_generates(monkeypatch):
    monkeypatch.setattr(
        graph,
        "retrieve_documents",
        lambda query: [Document(page_content="context one")],
    )
    monkeypatch.setattr(
        graph,
        "get_llm",
        lambda: type("FakeLLM", (), {"invoke": lambda self, p: FakeResponse("graph answer")})(),
    )

    result = graph.graph.invoke({"question": "my question"})

    assert result["answer"] == "graph answer"
    assert result["context"] == "context one"
    assert [doc.page_content for doc in result["documents"]] == ["context one"]


def test_context_joins_all_documents(monkeypatch):
    monkeypatch.setattr(
        graph,
        "retrieve_documents",
        lambda query: [
            Document(page_content="chunk one"),
            Document(page_content="chunk two"),
        ],
    )
    monkeypatch.setattr(
        graph,
        "get_llm",
        lambda: type("FakeLLM", (), {"invoke": lambda self, p: FakeResponse("done")})(),
    )

    result = graph.graph.invoke({"question": "my question"})

    assert result["context"] == "chunk one\n\nchunk two"


def test_generate_prompt_contains_context_and_question(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        graph,
        "retrieve_documents",
        lambda query: [Document(page_content="context one")],
    )
    monkeypatch.setattr(
        graph,
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

    graph.graph.invoke({"question": "my question"})

    rendered = str(captured["prompt"])
    assert "context one" in rendered
    assert "my question" in rendered


def test_empty_retrieval_still_generates(monkeypatch):
    monkeypatch.setattr(graph, "retrieve_documents", lambda query: [])
    monkeypatch.setattr(
        graph,
        "get_llm",
        lambda: type("FakeLLM", (), {"invoke": lambda self, p: FakeResponse("no docs")})(),
    )

    result = graph.graph.invoke({"question": "my question"})

    assert result["answer"] == "no docs"
    assert result["context"] == ""
