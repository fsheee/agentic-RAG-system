"""Embedding model factory.

Two providers are supported, chosen by the model name:

- ``models/...`` / ``gemini...`` -> Gemini API embeddings (no local ML
  runtime, so the serverless bundle stays small).
- anything else -> local sentence-transformers (optional
  ``local-embeddings`` extra, which is what pulls in torch).

Imports for both providers are lazy: importing this module must not require
torch, otherwise the Vercel function would need the whole ML stack even when
Gemini embeddings are configured.
"""

from app.config import EMBEDDING_MODEL


def _is_gemini(model: str) -> bool:
    return model.startswith("models/") or model.startswith("gemini")


def _gemini_embeddings(model: str):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(model=model)


def _huggingface_embeddings(model: str):
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "Local embeddings need the 'local-embeddings' extra. Install it "
            "with: uv sync --extra local-embeddings"
        ) from exc

    return HuggingFaceEmbeddings(model_name=model)


def get_embeddings():
    """Create the configured embedding model."""
    if not EMBEDDING_MODEL:
        raise ValueError(
            "EMBEDDING_MODEL is not set. Add it to your .env file."
        )

    if _is_gemini(EMBEDDING_MODEL):
        return _gemini_embeddings(EMBEDDING_MODEL)

    return _huggingface_embeddings(EMBEDDING_MODEL)
