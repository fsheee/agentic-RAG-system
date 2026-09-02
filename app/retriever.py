from .config import RETRIEVAL_THRESHOLD
from .vectorstore import create_vector_store


def retrieve_documents(query: str, k: int = 3, min_relevance: float | None = None):
    """
    Retrieve the most relevant documents from Qdrant.

    Chunks whose relevance score is below the threshold are dropped so
    obviously unrelated documents never reach the LLM: an empty retrieval
    yields "I don't know based on the provided documents." instead of a
    forced answer from noise.
    """
    if min_relevance is None:
        min_relevance = RETRIEVAL_THRESHOLD

    vector_store = create_vector_store()

    scored = vector_store.similarity_search_with_relevance_scores(query, k=k)

    return [
        document
        for document, score in scored
        if score >= min_relevance
    ]


if __name__ == "__main__":
    query = "What are the PROBATION PERIOD ?"

    documents = retrieve_documents(query)

    for i, document in enumerate(documents, 1):
        print(f"\n--- Result {i} ---")
        print(document.page_content)
        print("Metadata:", document.metadata)
