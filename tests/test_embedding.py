import pytest

from app import embedding


def test_raises_when_embedding_model_not_configured(monkeypatch):
    monkeypatch.setattr(embedding, "EMBEDDING_MODEL", None)

    with pytest.raises(ValueError, match="EMBEDDING_MODEL is not set"):
        embedding.get_embeddings()


def test_passes_configured_model_to_huggingface(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        embedding,
        "EMBEDDING_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    monkeypatch.setattr(
        embedding,
        "HuggingFaceEmbeddings",
        lambda **kwargs: captured.update(kwargs) or "embeddings",
    )

    result = embedding.get_embeddings()

    assert result == "embeddings"
    assert (
        captured["model_name"]
        == "sentence-transformers/all-MiniLM-L6-v2"
    )