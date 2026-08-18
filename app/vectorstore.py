from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models

from .embedding import get_embeddings


COLLECTION_NAME = "hospital_knowledge"


def create_vector_store():
    embeddings = get_embeddings()

    client = QdrantClient(path="qdrant_data")

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



# from langchain_qdrant import QdrantVectorStore
# from qdrant_client import QdrantClient

# from embedding import get_embeddings


# COLLECTION_NAME = "hospital_knowledge"


# def create_vector_store():
#     embeddings = get_embeddings()

#     client = QdrantClient(path="qdrant_data")

#     vector_store = QdrantVectorStore(
#         client=client,
#         collection_name=COLLECTION_NAME,
#         embedding=embeddings,
#     )

#     return vector_store