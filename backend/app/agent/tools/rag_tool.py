from app.core import ask


def search_knowledge_base(
    question: str,
    access: set[str] | None = None,
    history: list[dict] | None = None,
) -> dict:
    """
    Thin RAG tool: delegates entirely to the shared Phase 1 core.

    Returns {answer, sources, documents}. No retrieval or generation
    logic lives here.

    `access` is the set of document tiers the caller may read; the agent
    passes the tiers for the requesting user's role (see app/access.py).

    `history` is prior turns, forwarded so a follow-up question can be
    rewritten into a standalone retrieval query. Sanitisation happens in
    core.format_history.
    """
    return ask(question, access=access, history=history)
