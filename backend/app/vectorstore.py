import os
from pathlib import Path

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models

from .config import QDRANT_COLLECTION_PREFIX, QDRANT_URL
from .embedding import get_embeddings


BASE_COLLECTION_NAME = "hospital_knowledge"

COLLECTION_NAME = (
    f"{QDRANT_COLLECTION_PREFIX}_{BASE_COLLECTION_NAME}"
    if QDRANT_COLLECTION_PREFIX
    else BASE_COLLECTION_NAME
)

# Local-mode Qdrant must resolve to the same store for every process:
# ingest runs from the repo root, the API server runs from backend/, and a
# relative "qdrant_data" silently opened a second, empty collection in
# whichever cwd the process happened to start in. Anchored to the repo root
# (vectorstore.py -> app -> backend -> repo) so it is cwd-independent.
# QDRANT_PATH overrides the location when set.
_DEFAULT_QDRANT_PATH = Path(__file__).resolve().parents[2] / "qdrant_data"
QDRANT_PATH = Path(os.getenv("QDRANT_PATH") or _DEFAULT_QDRANT_PATH)


def create_vector_store():
    embeddings = get_embeddings()

    if QDRANT_URL:
        client = QdrantClient(url=QDRANT_URL)
    else:
        client = QdrantClient(path=str(QDRANT_PATH))

    if not client.collection_exists(COLLECTION_NAME):
        vector_size = len(embeddings.embed_query("test"))

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    return QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )