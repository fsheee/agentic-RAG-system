from .vectorstore import create_vector_store


def retrieve_documents(query: str, k: int = 3):
    """
    Retrieve the most relevant documents from Qdrant.
    """

    vector_store = create_vector_store()

    documents = vector_store.similarity_search(
        query,
        k=k,
    )

    return documents


if __name__ == "__main__":
    query = "What are the PROBATION PERIOD ?"

    documents = retrieve_documents(query)

    for i, document in enumerate(documents, 1):
        print(f"\n--- Result {i} ---")
        print(document.page_content)
        print("Metadata:", document.metadata)