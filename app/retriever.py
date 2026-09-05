from .config import RETRIEVAL_THRESHOLD, SCORE_MARGIN
from .vectorstore import create_vector_store


def retrieve_documents(query: str, k: int = 3, min_relevance: float | None = None):
    """
    Retrieve the most relevant documents from Qdrant.

    Two filters drop chunks that would produce false citations:

    1. Absolute: chunks below RETRIEVAL_THRESHOLD never reach the LLM.
    2. Relative: chunks scoring far below the best match are dropped even
       if they clear the absolute threshold — a loosely-related chunk
       (e.g. the HR handbook for a "hospital location" question) would
       otherwise be cited as a source without supporting the answer.
    """
    if min_relevance is None:
        min_relevance = RETRIEVAL_THRESHOLD

    vector_store = create_vector_store()

    scored = vector_store.similarity_search_with_relevance_scores(query, k=k)

    scored = [
        (document, score)
        for document, score in scored
        if score >= min_relevance
    ]

    if scored:
        best = scored[0][1]  # results are sorted by score
        scored = [
            (document, score)
            for document, score in scored
            if best - score <= SCORE_MARGIN
        ]

    return [document for document, _ in scored]


if __name__ == "__main__":
    query = "What are the PROBATION PERIOD ?"

    documents = retrieve_documents(query)

    for i, document in enumerate(documents, 1):
        print(f"\n--- Result {i} ---")
        print(document.page_content)
        print("Metadata:", document.metadata)
