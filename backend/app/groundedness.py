"""
Groundedness: does the retrieved context actually support the answer?

This is a validation step, not a second RAG implementation — it never
retrieves and never generates, it only judges an answer against the exact
blocks the model was shown. Generation stays in app/core.py.
"""

from app.core import _extract_text, format_blocks
from app.llm import get_llm
from app.prompt import GROUNDING_PROMPT


def is_grounded(answer: str, documents: list) -> bool:
    """
    Whether the retrieved documents support `answer`.

    `documents` must be the same list the answer was generated from — the
    access-restricted one — so the judge is never shown, and never needs,
    anything the caller could not read.

    Empty retrieval is trivially grounded: core already answered "I don't
    know based on the provided documents." there is nothing to contradict.

    Deliberately fails open. An unreachable judge, a non-committal reply or
    an unparsable verdict all leave the answer standing: a wrong refusal
    discards an answer that may be perfectly fine, while a missed check
    only leaves the behaviour we already have. Retrieval has already been
    through the relevance threshold, so this is one call spent on catching
    a model that answered from memory instead of from the chunks.
    """
    if not documents or not answer.strip():
        return True

    try:
        prompt = GROUNDING_PROMPT.invoke(
            {
                "context": "\n\n".join(format_blocks(documents)),
                "answer": answer,
            }
        )
        response = get_llm().invoke(prompt)
        verdict = _extract_text(response).strip().upper()
    except Exception as e:
        print(f"Groundedness check error: {e}")
        return True

    if verdict.startswith("UNSUPPORTED") or "NOT SUPPORTED" in verdict:
        return False

    # "SUPPORTED" and anything unparsable both pass: fail open.
    return True
