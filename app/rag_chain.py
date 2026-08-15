from llm import get_llm
from retriever import retrieve_documents


def generate_answer(query: str) -> str:
    documents = retrieve_documents(query)

    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    prompt = f"""
You are a helpful hospital assistant.

Answer the user's question using only the information in the context.
If the context does not contain the answer, say that you don't know.

Context:
{context}

Question:
{query}

Answer:
"""

    llm = get_llm()
    response = llm.invoke(prompt)

    return response.content


# if __name__ == "__main__":
#     question = "What are the  PROBATION PERIOD?"
#     answer = generate_answer(question)

#     print("Answer:")
#     print(answer)