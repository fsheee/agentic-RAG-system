from app.core import ask


def search_knowledge_base(question: str) -> dict:
    """
    Thin RAG tool: delegates entirely to the shared Phase 1 core.

    Returns {answer, sources, documents}. No retrieval or generation
    logic lives here.
    """
    return ask(question)
