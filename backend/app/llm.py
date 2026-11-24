import logging

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

logger = logging.getLogger(__name__)


class FallbackLLM:
    """Try the primary model, then a second provider on any failure.

    Provider outages (429/503 "high demand", timeouts, dropped connections)
    are transient, and without this they surface as a 500 from /ask even
    though another configured provider could have answered. Both chat models
    accept the same prompt and return the same message shape, so callers do
    not need to know which one answered.
    """

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def invoke(self, input, *args, **kwargs):
        try:
            return self.primary.invoke(input, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - any provider failure is retryable
            logger.warning(
                "primary LLM failed (%s: %s); retrying with fallback provider",
                type(exc).__name__,
                exc,
            )
            return self.fallback.invoke(input, *args, **kwargs)


def _gemini_llm():
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        api_key=GOOGLE_API_KEY,
        temperature=0,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


def _groq_llm():
    return ChatGroq(
        model=MODEL_NAME,
        api_key=GROQ_API_KEY,
        temperature=0,
        request_timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


def get_llm():
    """Return the chat model with a bounded call budget.

    Without a timeout a stalled provider call pins a worker thread until the
    client gives up; without retries a single dropped packet turns into a
    failed request. Both limits are enforced by the provider SDK.

    Gemini is preferred when configured, but a Groq fallback is attached
    whenever a Groq key is present: a Gemini outage then degrades to a
    slightly different model instead of taking the API down.
    """
    if GOOGLE_API_KEY:
        primary = _gemini_llm()

        if GROQ_API_KEY and MODEL_NAME:
            return FallbackLLM(primary, _groq_llm())

        return primary

    return _groq_llm()
