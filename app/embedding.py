from langchain_huggingface import HuggingFaceEmbeddings
from app.config import EMBEDDING_MODEL


def get_embeddings():
    """
    Create the embedding model.
    """

    if not EMBEDDING_MODEL:
        raise ValueError(
            "EMBEDDING_MODEL is not set. Add it to your .env file."
        )

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL
    )

    return embeddings