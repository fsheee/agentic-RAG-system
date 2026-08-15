
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader


DATA_PATH = "knowledge_base"


def load_documents():
    """
    Load PDF and TXT files from the knowledge base.
    """

    documents = []

    for file in Path(DATA_PATH).iterdir():
        if file.suffix.lower() == ".pdf":
            loader = PyPDFLoader(str(file))
            documents.extend(loader.load())

        elif file.suffix.lower() == ".txt":
            loader = TextLoader(str(file), encoding="utf-8")
            documents.extend(loader.load())

    return documents
# from pathlib import Path

# from langchain_community.document_loaders import PyPDFLoader


# DATA_PATH = "knowledge_base"


# def load_documents():
#     """
#     Load all PDF files from the knowledge base.
#     """

#     documents = []

#     pdf_files = Path(DATA_PATH).glob("*.pdf")

#     for pdf in pdf_files:
#         loader = PyPDFLoader(str(pdf))
#         documents.extend(loader.load())

#     return documents
