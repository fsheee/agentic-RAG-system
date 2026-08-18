from .llm import get_llm
from .prompt import RAG_PROMPT
from .retriever import retrieve_documents


def generate_answer(query: str) -> str:
    # Retrieve relevant documents from Qdrant
    documents = retrieve_documents(query)

    # Combine retrieved document chunks into context
    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    # Fill the prompt template
    prompt = RAG_PROMPT.invoke(
        {
            "context": context,
            "input": query,
        }
    )

    # Generate answer using the LLM
    llm = get_llm()
    response = llm.invoke(prompt)

    return response.content


# if __name__ == "__main__":
#     question = "What is the probation period?"
#     answer = generate_answer(question)

#     print("\nAnswer:")
#     print(answer)