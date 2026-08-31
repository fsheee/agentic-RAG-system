import json
from pathlib import Path

import pytest

from app.guardrails import check_user_input

CASES = json.loads((Path(__file__).parent.parent / "eval" / "guardrail_cases.json").read_text())


def _metrics():
    false_negatives = [
        case["text"] for case in CASES
        if case["blocked"] and check_user_input(case["text"]) is None
    ]
    false_positives = [
        case["text"] for case in CASES
        if not case["blocked"] and check_user_input(case["text"]) is not None
    ]
    return false_negatives, false_positives


def test_no_injection_attempts_slip_through():
    false_negatives, _ = _metrics()
    assert false_negatives == [], f"Missed injections: {false_negatives}"


def test_benign_questions_are_not_blocked():
    _, false_positives = _metrics()
    assert false_positives == [], f"Over-blocked benign questions: {false_positives}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["text"][:40])
def test_each_case(case):
    blocked = check_user_input(case["text"]) is not None
    assert blocked is case["blocked"]
