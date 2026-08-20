import importlib

import pytest

from app import config, vectorstore


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.exists = False

    def collection_exists(self, name):
        return self.exists

    def create_collection(self, **kwargs):
        self.created = kwargs


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3, 0.4]


def _reload(monkeypatch, **overrides):
    settings = {
        "QDRANT_URL": None,
        "QDRANT_COLLECTION_PREFIX": None,
    }
    settings.update(overrides)

    monkeypatch.setattr(config, "QDRANT_URL", settings["QDRANT_URL"])
    monkeypatch.setattr(
        config,
        "QDRANT_COLLECTION_PREFIX",
        settings["QDRANT_COLLECTION_PREFIX"],
    )

    module = importlib.reload(vectorstore)

    monkeypatch.setattr(module, "QdrantVectorStore", lambda **kwargs: "vector_store")
    monkeypatch.setattr(module, "get_embeddings", FakeEmbeddings)

    return module


def _client(module, monkeypatch, exists=False):
    fake_client = FakeClient()
    fake_client.exists = exists

    def make_client(**kwargs):
        fake_client.kwargs = kwargs
        return fake_client

    monkeypatch.setattr(module, "QdrantClient", make_client)
    return fake_client


def test_uses_local_path_when_no_qdrant_url(monkeypatch):
    module = _reload(monkeypatch)
    fake_client = _client(module, monkeypatch)

    module.create_vector_store()

    assert fake_client.kwargs["path"] == "qdrant_data"


def test_uses_remote_url_when_set(monkeypatch):
    module = _reload(monkeypatch, QDRANT_URL="http://localhost:6333")
    fake_client = _client(module, monkeypatch)

    module.create_vector_store()

    assert fake_client.kwargs["url"] == "http://localhost:6333"


def test_collection_name_gets_prefix(monkeypatch):
    module = _reload(
        monkeypatch,
        QDRANT_COLLECTION_PREFIX="healthcare",
    )

    assert module.COLLECTION_NAME == "healthcare_hospital_knowledge"


def test_collection_name_without_prefix(monkeypatch):
    module = _reload(monkeypatch)

    assert module.COLLECTION_NAME == "hospital_knowledge"


def test_creates_collection_when_missing(monkeypatch):
    module = _reload(monkeypatch)
    fake_client = _client(module, monkeypatch)

    module.create_vector_store()

    assert fake_client.created["collection_name"] == "hospital_knowledge"
    assert fake_client.created["vectors_config"].size == 4
    assert fake_client.created["vectors_config"].distance.name == "COSINE"


def test_skips_creation_when_collection_exists(monkeypatch):
    module = _reload(monkeypatch)
    fake_client = _client(module, monkeypatch, exists=True)

    module.create_vector_store()

    assert not hasattr(fake_client, "created")