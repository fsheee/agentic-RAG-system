from qdrant_client.http import models

from .config import RETRIEVAL_THRESHOLD, SCORE_MARGIN
from .vectorstore import create_vector_store


def _access_filter(access: set[str] | None) -> models.Filter | None:
    """
    Qdrant payload filter restricting results to the given access tiers.

    The tier is stored under the document metadata, which langchain_qdrant
    nests under the payload's "metadata" key, hence the dotted path.

    Note the `is None` test rather than a truthiness test: an empty set is
    falsy but must mean "match nothing", the opposite of None ("no filter").
    """
    if access is None:
        return None

    return models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.access",
                match=models.MatchAny(any=sorted(access)),
            )
        ]
    )


def retrieve_documents(
    query: str,
    k: int = 3,
    min_relevance: float | None = None,
    access: set[str] | None = None,
):
    """
    Retrieve the most relevant documents from Qdrant.

    `access` is the set of access tiers the caller may read (see
    app/access.py). Chunks outside those tiers are filtered out by Qdrant
    itself, so they are never candidates, never reach the prompt and can
    never be cited.

    `access=None` disables filtering and is reserved for non-HTTP callers
    that have no role: the CLI, the golden eval, and the rag_chain
    compatibility shim. Callers serving a request must always pass a set
    derived from the caller's role.

    Two further filters drop chunks that would produce false citations:

    1. Absolute: chunks below RETRIEVAL_THRESHOLD never reach the LLM.
    2. Relative: chunks scoring far below the best match are dropped even
       if they clear the absolute threshold — a loosely-related chunk
       (e.g. the HR handbook for a "hospital location" question) would
       otherwise be cited as a source without supporting the answer.
    """
    if min_relevance is None:
        min_relevance = RETRIEVAL_THRESHOLD

    vector_store = create_vector_store()

    scored = vector_store.similarity_search_with_relevance_scores(
        query,
        k=k,
        filter=_access_filter(access),
    )

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
