from app.llm import get_llm
from app.retriever import retrieve_documents


def rag_agent(state):
    question = state["question"]

    documents = retrieve_documents(question)

    if not documents:
        return {
            "context": "",
            "answer": "I couldn't find relevant information in the knowledge base.",
        }

    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    llm = get_llm()

    prompt = f"""
You are a healthcare knowledge assistant.

Answer the question using only the provided context.
If the answer is not in the context, say you don't know.

Context:
{context}

Question:
{question}
"""

    response = llm.invoke(prompt)

    return {
        "context": context,
        "answer": response.content,
    }