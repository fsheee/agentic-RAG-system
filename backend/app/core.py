import re

from app.guardrails import sanitize_context
from app.llm import get_llm
from app.prompt import RAG_PROMPT
from app.retriever import retrieve_documents


def build_context(question: str, access: set[str] | None = None) -> tuple[list, list[str]]:
    """
    Retrieve relevant documents and build numbered context blocks.

    Shared by every consumer (CLI, API, LangGraph nodes) so retrieval exists
    in exactly one place. Retrieved chunks are untrusted content, so each
    block is sanitized before it is used in a prompt.

    `access` is the set of document tiers the caller may read; see
    app/access.py. Callers serving a request must pass one.

    Blocks are numbered so the LLM can cite the ones it actually used —
    a retrieved-but-unused chunk (e.g. an HR handbook for a hospital
    location question) must not appear as a source.
    """
    documents = retrieve_documents(question, access=access)

    blocks = [
        f"[{i}] {sanitize_context(document.page_content)}"
        for i, document in enumerate(documents, 1)
    ]

    return documents, blocks


# Cap on the rendered history block, independent of the per-message cap in
# crud.MAX_MESSAGE_CHARS. Oldest turns are dropped once it is exceeded.
HISTORY_MAX_CHARS = 4000


def format_history(history: list[dict] | None) -> str:
    """
    Render past conversation turns for the prompt.

    History is untrusted on replay: a stored turn can contain an injection
    attempt that the guardrail blocked for the live turn, and assistant
    turns embed retrieved-document text. Each message is therefore
    neutralised with sanitize_context — the same treatment retrieved chunks
    get in build_context.

    Note this deliberately does NOT reuse check_user_input: that function's
    job is to *reject* a turn, and rejecting here would abort every later
    question in a conversation whose first turn once tripped a pattern.

    When the rendered text exceeds HISTORY_MAX_CHARS the oldest turns are
    dropped, so the most recent context always survives.
    """
    if not history:
        return ""

    lines: list[str] = []
    total = 0

    for message in reversed(history):
        content = sanitize_context(str(message.get("content", "")))
        who = "User" if message.get("role") == "user" else "Assistant"
        line = f"{who}: {content}"

        if total + len(line) > HISTORY_MAX_CHARS:
            break

        lines.append(line)
        total += len(line)

    return "\n".join(reversed(lines))


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

# Trailing "Sources: 1, 2" line the prompt asks the LLM to emit. The model
# also writes "Sources:" or "Sources: None" when it cites nothing; those must
# strip too, otherwise the line stays inside the answer, the answer stops
# matching UNKNOWN_ANSWER, and the fallback below cites every retrieved
# document for an answer that cites none.
SOURCES_LINE = re.compile(r"^sources?:\s*(?:none|[\d\s,]*)\s*$", re.IGNORECASE)


def _split_answer_and_sources(answer: str) -> tuple[str, list[int] | None]:
    """
    Split a trailing "Sources: <numbers>" line off the answer.

    Returns (answer, cited block numbers):
    - None  -> the model emitted no Sources line at all; the caller falls
      back to citing every retrieved document.
    - []    -> the model emitted "Sources:" / "Sources: None", i.e. it cited
      nothing; the caller reports no sources.
    """
    lines = answer.strip().rsplit("\n", 1)

    if len(lines) == 2 and SOURCES_LINE.fullmatch(lines[1].strip()):
        numbers = re.findall(r"\d+", lines[1])
        return lines[0].strip(), [int(n) for n in numbers]

    return answer.strip(), None


def ask(
    question: str,
    access: set[str] | None = None,
    history: list[dict] | None = None,
) -> dict:
    """
    The single reusable RAG entry point.

    question -> {answer, sources, documents}

    `access` restricts retrieval to the given document tiers; see
    app/access.py. Callers serving an authenticated or public request must
    pass the tiers for that caller's role.

    `history` is prior turns as [{"role", "content"}] dicts — plain data,
    never ORM objects, so this module stays free of any database import.
    It is optional: the CLI, the golden eval and rag_chain pass no history.

    Retrieval still embeds `question` alone; history informs the answer, it
    does not rewrite the query (see the plan's out-of-scope note).
    """
    try:
        documents, blocks = build_context(question, access=access)

        prompt = RAG_PROMPT.invoke(
            {
                "history": format_history(history),
                "context": "\n\n".join(blocks),
                "input": question,
            }
        )

        response = get_llm().invoke(prompt)

        answer, cited = _split_answer_and_sources(_extract_text(response))

        # No grounded answer -> no citations. Retrieving a document is not
        # the same as it supporting an answer. The same holds when the model
        # explicitly cites nothing ("Sources: None").
        if answer == UNKNOWN_ANSWER or cited == []:
            sources = []
        elif cited is None:
            # Model omitted the Sources line -> keep the previous behavior
            # of citing every retrieved document. This is only safe because
            # `documents` is already restricted to the caller's access tiers
            # — anything that widens or re-merges this list (an unfiltered
            # retry, a cache of another role's results) would turn this line
            # into a leak.
            sources = format_sources(documents)
        else:
            supported = [
                documents[number - 1]
                for number in cited
                if 1 <= number <= len(documents)
            ]
            # Numbers matching no retrieved block are meaningless; fall back
            # to the same access-restricted list as above.
            sources = format_sources(supported or documents)

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
