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
    """Probe with an on-topic question: the relevance threshold filters
    off-topic probes (correctly) to nothing, which would look like
    'retrieval unavailable'."""
    try:
        return bool(retrieve_documents(GOLDEN[0]["question"], k=1))
    except Exception:
        return False


@pytest.mark.skipif(not _retrieval_enabled(), reason="Qdrant/knowledge base unavailable")
def test_retrieval_hit_rate():
    hits = 0
    misses = []

    for case in GOLDEN:
        documents = retrieve_documents(case["question"])
        sources = [document.metadata.get("source", "") for document in documents]
        expected = case["expected_source"]

        # expected_source: null marks a question the knowledge base cannot
        # answer. The relevance threshold must drop everything there —
        # retrieving an off-topic chunk is a miss, not a near miss.
        if expected is None:
            if not documents:
                hits += 1
            else:
                misses.append(f"{case['question']!r}: retrieved {sources}")
        elif any(source.endswith(expected) for source in sources):
            hits += 1
        else:
            misses.append(f"{case['question']!r}: expected {expected}, got {sources}")

    hit_rate = hits / len(GOLDEN)
    assert hit_rate >= MIN_HIT_RATE, (
        f"Retrieval hit rate {hit_rate:.2f} < {MIN_HIT_RATE}. "
        f"Misses:\n" + "\n".join(misses)
    )
