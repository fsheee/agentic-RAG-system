"""Deterministic small-talk handling.

Greetings are answered in Python, not by the LLM. The RAG prompt is required
to answer only from retrieved context, so routing "hi" through it would
either invent an answer or reply "I don't know based on the provided
documents." A fixed reply also costs no tokens and cannot be hijacked by
prompt injection.
"""

import re

# A message that is *only* a greeting/pleasantry. "hi, what are the visiting
# hours?" is deliberately not a greeting: the question is what matters, so
# that turn must still reach retrieval.
GREETING_RE = re.compile(
    r"""
    ^\s*
    (?:
        hi+|hello+|hey+|hiya|yo|hola
      | salaam|salam
      | assalam(?:u)?[\s\-]*(?:alaikum|o[\s\-]*alaikum)
      | good\s+(?:morning|afternoon|evening|day)
      | greetings
    )
    (?:[\s,!.]+(?:there|everyone|team|again|sir|madam|doctor|all))*
    \s*[!.?]*\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

GREETING_REPLY = (
    "Hello! Welcome to the hospital assistant. I can help with hospital "
    "policies and visiting hours, doctors and their consultation fees, or "
    "booking and viewing appointments. How can I help you today?"
)


def is_greeting(text: str | None) -> bool:
    """True when the whole message is a greeting with no actual request."""
    return bool(text and GREETING_RE.match(text))
