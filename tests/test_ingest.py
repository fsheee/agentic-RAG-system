from langchain_core.documents import Document

from app.ingest import chunk_ids, ingest_documents, remove_stale_vectors


def make_chunks():
    return [
        Document(
            page_content="Visiting hours are 8 AM to 8 PM.",
            metadata={"source": "hospital_policy.pdf", "page": 0},
        ),
        Document(
            page_content="Patients must bring a valid ID.",
            metadata={"source": "hospital_policy.pdf", "page": 0},
        ),
        Document(
            page_content="Probation period is three months.",
            metadata={"source": "hr_policy.txt", "page": 2},
        ),
    ]


def test_ids_are_deterministic():
    ids_1 = chunk_ids(make_chunks())
    ids_2 = chunk_ids(make_chunks())

    assert ids_1 == ids_2


def test_ids_are_unique_per_chunk():
    ids = chunk_ids(make_chunks())

    assert len(ids) == len(set(ids))


def test_same_content_same_source_page_gets_distinct_ids():
    chunks = [
        Document(page_content="same", metadata={"source": "a.pdf", "page": 0}),
        Document(page_content="same", metadata={"source": "a.pdf", "page": 0}),
    ]

    assert len(set(chunk_ids(chunks))) == 2


def test_changed_content_keeps_same_id():
    """A chunk edit must update the existing point, not add a new one."""
    chunks = make_chunks()
    chunks[0] = Document(
        page_content="Visiting hours are 9 AM to 9 PM.",
        metadata={"source": "hospital_policy.pdf", "page": 0},
    )

    assert chunk_ids(chunks)[0] == chunk_ids(make_chunks())[0]


def test_missing_metadata_still_produces_stable_ids():
    chunks = [Document(page_content="no metadata")]

    assert chunk_ids(chunks) == chunk_ids(chunks)


class FakePoint:
    def __init__(self, id):
        self.id = id


class FakeClient:
    def __init__(self, existing_ids):
        self.existing_ids = existing_ids
        self.deleted = []

    def scroll(self, collection_name, with_payload, with_vectors, limit, offset):
        batch = [FakePoint(i) for i in sorted(self.existing_ids)]
        # single page: return everything, offset None ends the loop
        return batch, None

    def delete(self, collection_name, points_selector):
        self.deleted.append((collection_name, points_selector))


class FakeVectorStore:
    def __init__(self, existing_ids):
        self.client = FakeClient(existing_ids)
        self.collection_name = "hospital_knowledge"


def test_remove_stale_vectors_deletes_only_missing_ids():
    current = ["a", "b"]
    store = FakeVectorStore(existing_ids={"a", "b", "c", "d"})

    stale = remove_stale_vectors(store, current)

    assert stale == ["c", "d"]
    assert store.client.deleted == [("hospital_knowledge", ["c", "d"])]


def test_remove_stale_vectors_noop_when_nothing_stale():
    current = ["a", "b"]
    store = FakeVectorStore(existing_ids={"a", "b"})

    assert remove_stale_vectors(store, current) == []
    assert store.client.deleted == []


def test_ingest_documents_uses_ids_for_idempotency(monkeypatch):
    """add_documents must be called with deterministic ids (enables upsert)."""
    from app import ingest

    chunks = make_chunks()

    class RecordingStore:
        def __init__(self):
            self.calls = []
            self.client = FakeClient(set())
            self.collection_name = "hospital_knowledge"

        def add_documents(self, documents, ids=None):
            self.calls.append((documents, ids))

    store = RecordingStore()

    monkeypatch.setattr(ingest, "load_documents", lambda: chunks)
    monkeypatch.setattr(ingest, "split_documents", lambda docs: docs)
    monkeypatch.setattr(ingest, "create_vector_store", lambda: store)

    ingest_documents()

    documents, ids = store.calls[0]

    assert ids is not None
    assert len(ids) == len(documents)
    assert len(set(ids)) == len(ids)


def test_ingest_documents_removes_stale_points(monkeypatch, capsys):
    from app import ingest

    chunks = make_chunks()
    ids = chunk_ids(chunks)

    class RecordingStore:
        def __init__(self, existing):
            self.client = FakeClient(existing)
            self.collection_name = "hospital_knowledge"

        def add_documents(self, documents, ids=None):
            pass

    # one stale point left over from a removed document
    store = RecordingStore(existing=set(ids) | {"orphan-id"})

    monkeypatch.setattr(ingest, "load_documents", lambda: chunks)
    monkeypatch.setattr(ingest, "split_documents", lambda docs: docs)
    monkeypatch.setattr(ingest, "create_vector_store", lambda: store)

    ingest_documents()

    assert store.client.deleted == [("hospital_knowledge", ["orphan-id"])]
    assert "1 stale" in capsys.readouterr().out
