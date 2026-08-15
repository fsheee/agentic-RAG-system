from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from embedding import get_embeddings


COLLECTION_NAME = "hospital_knowledge"


def create_vector_store():
    embeddings = get_embeddings()

    client = QdrantClient(path="qdrant_data")

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )

    return vector_store