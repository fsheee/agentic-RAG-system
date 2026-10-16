"""Groundedness eval: does the judge call the right verdict on real text?

Unit tests cover parsing and failure handling with a fake model; this
exercises the actual prompt against the actual model, including the case
that matters most — a context that instructs the judge to pass the answer.
"""

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.config import GOOGLE_API_KEY, GROQ_API_KEY
from app.groundedness import is_grounded

CASES = json.loads(
    (Path(__file__).parent.parent / "eval" / "golden_groundedness.json").read_text()
)

pytestmark = pytest.mark.integration

MIN_ACCURACY = 0.75


@pytest.mark.skipif(
    not (GOOGLE_API_KEY or GROQ_API_KEY), reason="No LLM API key configured"
)
def test_grounding_accuracy():
    correct = 0
    failures = []

    for case in CASES:
        documents = [
            Document(
                page_content=case["context"],
                metadata={"source": "eval.pdf", "page": 0},
            )
        ]
        verdict = is_grounded(case["answer"], documents)

        if verdict is case["grounded"]:
            correct += 1
        else:
            failures.append(
                f"{case['answer']!r}: expected grounded={case['grounded']}, "
                f"got {verdict}"
            )

    accuracy = correct / len(CASES)
    assert accuracy >= MIN_ACCURACY, (
        f"Grounding accuracy {accuracy:.2f} < {MIN_ACCURACY}. "
        f"Failures:\n" + "\n".join(failures)
    )
