import hashlib
import uuid

from app.loader import load_documents
from app.splitter import split_documents
from app.vectorstore import create_vector_store


def chunk_ids(chunks) -> list[str]:
    """
    Deterministic IDs so re-ingesting the same documents upserts
    existing points instead of creating duplicates.

    The ID is stable for a given (source, page, chunk position), so:
    - unchanged document/chunk -> same ID -> upsert, no duplicate
    - changed chunk content -> same ID -> record updated
    - removed document -> its IDs disappear from the new set and are
      pruned by remove_stale_vectors()
    """
    counters: dict[tuple, int] = {}
    ids = []

    for chunk in chunks:
        key = (
            chunk.metadata.get("source", "unknown"),
            chunk.metadata.get("page", -1),
        )
        index = counters.get(key, 0)
        counters[key] = index + 1

        # Deterministic UUID (Qdrant local mode requires UUID point IDs):
        # first 16 bytes of the sha256 of (source, page, chunk position)
        digest = hashlib.sha256(f"{key[0]}:{key[1]}:{index}".encode()).digest()
        ids.append(str(uuid.UUID(bytes=digest[:16])))

    return ids


def _existing_point_ids(vector_store) -> set[str]:
    """All point IDs currently stored in the collection."""
    ids = set()
    offset = None

    while True:
        records, offset = vector_store.client.scroll(
            collection_name=vector_store.collection_name,
            with_payload=False,
            with_vectors=False,
            limit=256,
            offset=offset,
        )

        ids.update(point.id for point in records)

        if offset is None:
            break

    return ids


def remove_stale_vectors(vector_store, current_ids: list[str]) -> list[str]:
    """Delete points whose IDs are no longer produced by ingestion."""
    existing = _existing_point_ids(vector_store)
    stale = sorted(existing - set(current_ids))

    if stale:
        vector_store.client.delete(
            collection_name=vector_store.collection_name,
            points_selector=stale,
        )

    return stale


def ingest_documents():
    documents = load_documents()
    chunks = split_documents(documents)
    ids = chunk_ids(chunks)

    vector_store = create_vector_store()
    vector_store.add_documents(chunks, ids=ids)

    stale = remove_stale_vectors(vector_store, ids)

    print(f"Ingested {len(chunks)} chunks into Qdrant (upsert)")
    if stale:
        print(f"Removed {len(stale)} stale vectors")


if __name__ == "__main__":
    ingest_documents()
