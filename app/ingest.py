from .loader import load_documents
from .splitter import split_documents
from .vectorstore import create_vector_store


def ingest_documents():
    documents = load_documents()
    chunks = split_documents(documents)

    vector_store = create_vector_store()
    vector_store.add_documents(chunks)

    print(f"Added {len(chunks)} chunks to Qdrant")


if __name__ == "__main__":
    ingest_documents()