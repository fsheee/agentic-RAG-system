import re

from app.guardrails import sanitize_context
from app.llm import get_llm
from app.prompt import RAG_PROMPT
from app.retriever import retrieve_documents


def build_context(question: str) -> tuple[list, list[str]]:
    """
    Retrieve relevant documents and build numbered context blocks.

    Shared by every consumer (CLI, API, LangGraph nodes) so retrieval exists
    in exactly one place. Retrieved chunks are untrusted content, so each
    block is sanitized before it is used in a prompt.

    Blocks are numbered so the LLM can cite the ones it actually used —
    a retrieved-but-unused chunk (e.g. an HR handbook for a hospital
    location question) must not appear as a source.
    """
    documents = retrieve_documents(question)

    blocks = [
        f"[{i}] {sanitize_context(document.page_content)}"
        for i, document in enumerate(documents, 1)
    ]

    return documents, blocks


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


UNKNOWN_ANSWER = "I don't know based on the provided documents."

# Trailing "Sources: 1, 2" line the prompt asks the LLM to emit.
SOURCES_LINE = re.compile(r"^sources?:\s*[\d\s,]+$", re.IGNORECASE)


def _split_answer_and_sources(answer: str) -> tuple[str, list[int]]:
    """
    Split a trailing "Sources: <numbers>" line off the answer.

    Returns (answer, cited block numbers). An answer with no such line
    yields an empty list — the caller then falls back to citing all
    retrieved documents.
    """
    lines = answer.strip().rsplit("\n", 1)

    if len(lines) == 2 and SOURCES_LINE.fullmatch(lines[1].strip()):
        numbers = re.findall(r"\d+", lines[1])
        return lines[0].strip(), [int(n) for n in numbers]

    return answer.strip(), []


def ask(question: str) -> dict:
    """
    The single reusable RAG entry point.

    question -> {answer, sources, documents}
    """
    try:
        documents, blocks = build_context(question)

        prompt = RAG_PROMPT.invoke(
            {
                "context": "\n\n".join(blocks),
                "input": question,
            }
        )

        response = get_llm().invoke(prompt)

        answer, cited = _split_answer_and_sources(_extract_text(response))

        # No grounded answer -> no citations. Retrieving a document is not
        # the same as it supporting an answer.
        if answer == UNKNOWN_ANSWER:
            sources = []
        else:
            supported = [
                documents[number - 1]
                for number in cited
                if 1 <= number <= len(documents)
            ]
            # Model omitted the Sources line -> keep the previous
            # behavior of citing every retrieved document.
            if not supported:
                supported = documents

            sources = format_sources(supported)

        return {
            "answer": answer,
            "sources": sources,
            "documents": documents,
        }

    except Exception as e:
        print(f"RAG error: {e}")

        return {
            "answer": "Sorry, I couldn't generate an answer right now.",
            "sources": [],
            "documents": [],
        }
