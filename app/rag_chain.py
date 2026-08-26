from .llm import get_llm
from .prompt import RAG_PROMPT
from .retriever import retrieve_documents


def generate_answer(query: str) -> str:
    try:
        documents = retrieve_documents(query)

        context = "\n\n".join(
            document.page_content
            for document in documents
        )

        prompt = RAG_PROMPT.invoke(
            {
                "context": context,
                "input": query,
            }
        )

        llm = get_llm()
        response = llm.invoke(prompt)

        content = response.content

        if isinstance(content, list):
            answer = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            ).strip()
        else:
            answer = content

        sources = []

        for document in documents:
            source = document.metadata.get("source")
            page = document.metadata.get("page")

            if source:
                if page is not None:
                    sources.append(f"{source} — page {page + 1}")
                else:
                    sources.append(source)

        if sources:
            answer += "\n\nSources:\n" + "\n".join(
                f"- {source}" for source in dict.fromkeys(sources)
            )

        return answer

    except Exception as e:
        print(f"RAG error: {e}")
        return "Sorry, I couldn't generate an answer right now."

# from .llm import get_llm
# from .prompt import RAG_PROMPT
# from .retriever import retrieve_documents


# def generate_answer(query: str) -> str:
#     # Retrieve relevant documents from Qdrant
#     documents = retrieve_documents(query)

#     # Combine retrieved document chunks into context
#     context = "\n\n".join(
#         document.page_content
#         for document in documents
#     )

#     # Fill the prompt template
#     prompt = RAG_PROMPT.invoke(
#         {
#             "context": context,
#             "input": query,
#         }
#     )

#     # Generate answer using the LLM
#     llm = get_llm()
#     response = llm.invoke(prompt)

#     content = response.content

#     # Gemini returns content as a list of parts; join the text.
#     if isinstance(content, list):
#         return "".join(
#             part.get("text", "")
#             for part in content
#             if isinstance(part, dict)
#         ).strip()

#     return content


# if __name__ == "__main__":
#     question = "What is the probation period?"
#     answer = generate_answer(question)

#     print("\nAnswer:")
#     print(answer)