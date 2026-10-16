"""Answer-level eval: did the model use the chunk it was given?

The retrieval eval measures whether the right document came back. This one
measures whether the answer that came out actually says what the golden
case expects — the step where a correct retrieval can still turn into a
wrong answer.

Uses `answer_contains` from eval/golden_rag.json. Substring checks are
deliberately weak: they catch "the model ignored the chunk" without
asserting on phrasing.
"""

import json
from pathlib import Path

import pytest

from app.config import GOOGLE_API_KEY, GROQ_API_KEY
from app.core import ask
from app.retriever import retrieve_documents

GOLDEN = json.loads(
    (Path(__file__).parent.parent / "eval" / "golden_rag.json").read_text()
)

CASES = [case for case in GOLDEN if case["answer_contains"]]

pytestmark = pytest.mark.integration

# "two visitors" and "2 visitors" are the same answer. A digit term is
# accepted in either form so the eval measures whether the fact came
# through, not whether the model preferred numerals.
NUMBER_WORDS = {
    str(number): word
    for number, word in enumerate(
        [
            "zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen", "twenty", "twenty-one", "twenty-two", "twenty-three",
            "twenty-four", "twenty-five", "twenty-six", "twenty-seven",
            "twenty-eight", "twenty-nine", "thirty",
        ]
    )
}


def _term_matches(term: str, answer: str) -> bool:
    term = term.replace("’", "'").lower()
    if term in answer:
        return True
    return term.isdigit() and NUMBER_WORDS.get(term, "\0") in answer


def _retrieval_enabled() -> bool:
    """Probe with an on-topic question: the relevance threshold filters
    off-topic probes (correctly) to nothing, which would look like
    'retrieval unavailable'."""
    try:
        return bool(retrieve_documents(GOLDEN[0]["question"], k=1))
    except Exception:
        return False


AVAILABLE = bool(GOOGLE_API_KEY or GROQ_API_KEY) and _retrieval_enabled()


@pytest.mark.skipif(not AVAILABLE, reason="LLM or Qdrant unavailable")
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["question"][:40])
def test_answer_contains_expected_terms(case):
    result = ask(case["question"])
    # Typographic apostrophes ("don't") must not fail a correct refusal.
    answer = result["answer"].replace("’", "'").lower()

    missing = [
        term for term in case["answer_contains"] if not _term_matches(term, answer)
    ]

    assert not missing, (
        f"{case['question']!r}: answer {result['answer']!r} "
        f"is missing {missing}"
    )
