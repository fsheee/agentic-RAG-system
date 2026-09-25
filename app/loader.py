
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from app.access import access_for_source


DATA_PATH = "knowledge_base"

# TXT files have no pages, so we track location by line groups of this
# size and expose them as pseudo-pages in metadata (citations then show
# "page" for TXT sources instead of null).
TXT_PAGE_LINES = 40


def _load_txt_pages(file: Path) -> list[Document]:
    """Load a TXT file as line-based pseudo-pages with page metadata."""
    text = file.read_text(encoding="utf-8")
    lines = text.splitlines()

    documents = []
    for index, start in enumerate(range(0, len(lines), TXT_PAGE_LINES)):
        page_lines = lines[start:start + TXT_PAGE_LINES]
        content = "\n".join(page_lines).strip()
        if not content:
            continue

        documents.append(
            Document(
                page_content=content,
                metadata={
                    "source": str(file),
                    "page": index,
                    "access": access_for_source(str(file)),
                },
            )
        )

    return documents


def load_documents():
    """
    Load PDF and TXT files from the knowledge base.

    Every document carries an "access" tier in its metadata, which the
    retriever uses to filter results by the caller's role.
    """

    documents = []

    for file in Path(DATA_PATH).iterdir():
        if file.suffix.lower() == ".pdf":
            loader = PyPDFLoader(str(file))
            pages = loader.load()

            # PyPDFLoader supplies its own metadata; add the access tier
            # to each page rather than replacing what it found.
            for page in pages:
                page.metadata["access"] = access_for_source(str(file))

            documents.extend(pages)

        elif file.suffix.lower() == ".txt":
            documents.extend(_load_txt_pages(file))

    return documents
