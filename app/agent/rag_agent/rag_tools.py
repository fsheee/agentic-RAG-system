from langchain_core.tools import tool

from app.retriever import retrieve_documents


@tool
def search_hr_policy(question: str) -> str:
    """Search the HR policy documents for information relevant to the question."""

    documents = retrieve_documents(question)

    if not documents:
        return "No relevant information found in the HR policy."

    return "\n\n".join(
        document.page_content
        for document in documents
    )