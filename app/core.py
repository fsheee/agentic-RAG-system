from app.llm import get_llm
from app.prompt import RAG_PROMPT
from app.retriever import retrieve_documents


def build_context(question: str) -> tuple[list, str]:
    """
    Retrieve relevant documents and join them into context.

    Shared by every consumer (CLI, future API, LangGraph nodes)
    so retrieval exists in exactly one place.
    """
    documents = retrieve_documents(question)

    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    return documents, context


def format_sources(documents: list) -> list[dict]:
    """De-duplicated source citations: file + page, preserving order."""
    sources = []
    seen = set()

    for document in documents:
        source = document.metadata.get("source")
        page = document.metadata.get("page")

        if not source:
            continue

        key = (source, page)

        if key in seen:
            continue

        seen.add(key)
        sources.append({"source": source, "page": page + 1 if page is not None else None})

    return sources


def _extract_text(response) -> str:
    """Gemini returns content as a list of parts; join the text."""
    content = response.content

    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        ).strip()

    return content


def ask(question: str) -> dict:
    """
    The single reusable RAG entry point.

    question -> {answer, sources, documents}
    """
    try:
        documents, context = build_context(question)

        prompt = RAG_PROMPT.invoke(
            {
                "context": context,
                "input": question,
            }
        )

        response = get_llm().invoke(prompt)

        return {
            "answer": _extract_text(response),
            "sources": format_sources(documents),
            "documents": documents,
        }

    except Exception as e:
        print(f"RAG error: {e}")

        return {
            "answer": "Sorry, I couldn't generate an answer right now.",
            "sources": [],
            "documents": [],
        }
