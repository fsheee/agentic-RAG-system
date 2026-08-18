from langchain_core.prompts import ChatPromptTemplate


RAG_PROMPT = ChatPromptTemplate.from_template(
    """
You are a helpful healthcare assistant.

Answer the user's question ONLY using the provided context.

If the answer is not available in the context, simply reply:

"I don't know based on the provided documents."

Context:
{context}

Question:
{input}

Answer:
"""
)