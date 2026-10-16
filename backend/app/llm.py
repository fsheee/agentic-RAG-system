from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from .config import (
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    GROQ_API_KEY,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    MODEL_NAME,
)


def get_llm():
    """Return the chat model with a bounded call budget.

    Without a timeout a stalled provider call pins a worker thread until the
    client gives up; without retries a single dropped packet turns into a
    failed request. Both limits are enforced by the provider SDK.
    """
    if GOOGLE_API_KEY:
        return ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            api_key=GOOGLE_API_KEY,
            temperature=0,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )

    return ChatGroq(
        model=MODEL_NAME,
        api_key=GROQ_API_KEY,
        temperature=0,
        request_timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )