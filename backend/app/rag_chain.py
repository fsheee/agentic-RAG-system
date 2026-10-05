from .core import ask


def generate_answer(query: str) -> str:
    """
    Compatibility layer: delegates to the shared RAG core.

    Kept only while existing callers/tests use generate_answer().
    New code should call app.core.ask() directly.
    """
    result = ask(query)

    answer = result["answer"]

    if result["sources"]:
        answer += "\n\nSources:\n" + "\n".join(
            f"- {source['source']} — page {source['page']}"
            if source["page"] is not None
            else f"- {source['source']}"
            for source in result["sources"]
        )

    return answer
