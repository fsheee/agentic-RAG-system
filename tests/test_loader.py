from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.loader import load_documents


@pytest.fixture
def knowledge_base(tmp_path):
    from app import loader

    original = loader.DATA_PATH
    loader.DATA_PATH = str(tmp_path)
    yield tmp_path
    loader.DATA_PATH = original


def _write_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        writer.write(f)


def test_loads_txt_and_pdf_files(knowledge_base):
    (knowledge_base / "note.txt").write_text(
        "Patient visited for a routine checkup.", encoding="utf-8"
    )
    _write_pdf(knowledge_base / "policy.pdf")

    documents = load_documents()

    assert len(documents) == 2
    assert {"note.txt", "policy.pdf"} <= {
        Path(doc.metadata["source"]).name for doc in documents
    }


def test_skips_unsupported_file_types(knowledge_base):
    (knowledge_base / "notes.txt").write_text("hello", encoding="utf-8")
    (knowledge_base / "image.png").write_bytes(b"not really a png")

    documents = load_documents()

    assert len(documents) == 1
    assert Path(documents[0].metadata["source"]).suffix == ".txt"


def test_load_documents_when_knowledge_base_empty(tmp_path):
    from app import loader

    original = loader.DATA_PATH
    loader.DATA_PATH = str(tmp_path)
    try:
        assert load_documents() == []
    finally:
        loader.DATA_PATH = original


def test_txt_loaded_with_utf8_encoding(knowledge_base):
    text = "Chăm sóc bệnh nhân tại khoa nội."
    (knowledge_base / "viet.txt").write_text(text, encoding="utf-8")

    documents = load_documents()

    assert documents[0].page_content == text