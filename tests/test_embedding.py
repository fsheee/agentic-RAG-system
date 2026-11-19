import pytest

from app import embedding


def test_raises_when_embedding_model_not_configured(monkeypatch):
    monkeypatch.setattr(embedding, "EMBEDDING_MODEL", None)

    with pytest.raises(ValueError, match="EMBEDDING_MODEL is not set"):
        embedding.get_embeddings()


def test_gemini_model_uses_the_api_embeddings(monkeypatch):
    captured = {}

    monkeypatch.setattr(embedding, "EMBEDDING_MODEL", "models/gemini-embedding-001")
    monkeypatch.setattr(
        embedding,
        "_gemini_embeddings",
        lambda model: captured.update(model=model) or "embeddings",
    )
    monkeypatch.setattr(
        embedding,
        "_huggingface_embeddings",
        lambda model: pytest.fail("Gemini model must not load torch"),
    )

    assert embedding.get_embeddings() == "embeddings"
    assert captured["model"] == "models/gemini-embedding-001"


def test_huggingface_model_uses_local_embeddings(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        embedding, "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    monkeypatch.setattr(
        embedding,
        "_huggingface_embeddings",
        lambda model: captured.update(model=model) or "embeddings",
    )
    monkeypatch.setattr(
        embedding,
        "_gemini_embeddings",
        lambda model: pytest.fail("HF model must not call Gemini"),
    )

    assert embedding.get_embeddings() == "embeddings"
    assert captured["model"] == "sentence-transformers/all-MiniLM-L6-v2"
