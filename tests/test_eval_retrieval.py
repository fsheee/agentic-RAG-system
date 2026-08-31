import json
from pathlib import Path

import pytest

from app.retriever import retrieve_documents

GOLDEN = json.loads(
    (Path(__file__).parent.parent / "eval" / "golden_rag.json").read_text()
)

pytestmark = pytest.mark.integration

MIN_HIT_RATE = 0.7


def _retrieval_enabled() -> bool:
    try:
        return bool(retrieve_documents("test", k=1))
    except Exception:
        return False


@pytest.mark.skipif(not _retrieval_enabled(), reason="Qdrant/knowledge base unavailable")
def test_retrieval_hit_rate():
    hits = 0

    for case in GOLDEN:
        documents = retrieve_documents(case["question"])
        if any(
            document.metadata.get("source", "").endswith(case["expected_source"])
            for document in documents
        ):
            hits += 1

    hit_rate = hits / len(GOLDEN)
    assert hit_rate >= MIN_HIT_RATE, f"Retrieval hit rate {hit_rate:.2f} < {MIN_HIT_RATE}"
