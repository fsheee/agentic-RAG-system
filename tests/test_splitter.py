from langchain_core.documents import Document

from app.splitter import split_documents


LONG_TEXT = (
    "The hospital operates a 24-hour emergency department. "
    "Visiting hours are from 8 AM to 8 PM daily. "
    "Patients are asked to bring a valid ID at registration. "
    "Ward admission is coordinated through the nurse station. "
) * 50


def test_splits_long_documents_into_multiple_chunks():
    documents = [Document(page_content=LONG_TEXT)]

    chunks = split_documents(documents)

    assert len(chunks) > 1
    assert all(chunk.page_content for chunk in chunks)


def test_each_chunk_respects_chunk_size():
    documents = [Document(page_content=LONG_TEXT)]

    chunks = split_documents(documents)

    for chunk in chunks:
        assert len(chunk.page_content) <= 500


def test_preserves_document_metadata():
    document = Document(
        page_content=LONG_TEXT,
        metadata={"source": "hospital_policy.pdf", "page": 3},
    )

    chunks = split_documents([document])

    assert all(chunk.metadata["source"] == "hospital_policy.pdf" for chunk in chunks)
    assert all(chunk.metadata["page"] == 3 for chunk in chunks)


def test_short_document_stays_as_single_chunk():
    documents = [Document(page_content="Short note about visiting hours.")]

    chunks = split_documents(documents)

    assert len(chunks) == 1
    assert chunks[0].page_content == "Short note about visiting hours."


def test_empty_document_list_returns_empty():
    assert split_documents([]) == []