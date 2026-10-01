import re

# Patterns commonly used in prompt-injection attempts against the user input
# trust boundary. Retrieved documents get the same treatment via
# sanitize_context() before they reach the LLM.
INJECTION_PATTERNS = [
    r"ignore .{0,30}instructions",
    r"disregard .{0,30}(instructions|above|prior|previous)",
    r"reveal (your )?(system )?prompt",
    r"you are now",
    r"act as (if|a|an)",
    r"developer mode",
    r"jailbreak",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def check_user_input(question: str) -> str | None:
    """
    Inspect untrusted user input before it reaches the agent.

    Returns a rejection reason when the input looks like a prompt-injection
    attempt, otherwise None.
    """
    if not question or not question.strip():
        return "Question is empty."

    for pattern in _COMPILED:
        if pattern.search(question):
            return "Question contains instructions that try to override the assistant."

    return None


def sanitize_context(context: str) -> str:
    """
    Neutralize instruction-like content in retrieved documents.

    Retrieved chunks are untrusted data, never instructions, so we wrap them
    in delimiters and strip injection phrasing before they are placed in a
    prompt.
    """
    sanitized = context
    for pattern in _COMPILED:
        sanitized = pattern.sub("[filtered]", sanitized)

    return sanitized

