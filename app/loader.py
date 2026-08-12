from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader


DATA_PATH = "knowledge_base"


def load_documents():
    """
    Load all PDF files from the knowledge base.
    """

    documents = []

    pdf_files = Path(DATA_PATH).glob("*.pdf")

    for pdf in pdf_files:
        loader = PyPDFLoader(str(pdf))
        documents.extend(loader.load())

    return documents
