import json
from pathlib import Path

import pytest

from app.agent.graph import route_question
from app.config import GOOGLE_API_KEY, GROQ_API_KEY

GOLDEN = json.loads(
    (Path(__file__).parent.parent / "eval" / "golden_router.json").read_text()
)

pytestmark = pytest.mark.integration

MIN_ACCURACY = 0.75


@pytest.mark.skipif(
    not (GOOGLE_API_KEY or GROQ_API_KEY), reason="No LLM API key configured"
)
def test_router_accuracy():
    correct = 0
    failures = []

    for case in GOLDEN:
        predicted = route_question(case["question"])
        if predicted == case["route"]:
            correct += 1
        else:
            failures.append(
                f"{case['question']!r}: expected {case['route']}, got {predicted}"
            )

    accuracy = correct / len(GOLDEN)
    assert accuracy >= MIN_ACCURACY, (
        f"Router accuracy {accuracy:.2f} < {MIN_ACCURACY}. Failures:\n" + "\n".join(failures)
    )
