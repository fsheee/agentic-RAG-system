import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL_NAME = os.getenv("MODEL_NAME")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")

QDRANT_URL = os.getenv("QDRANT_URL")

QDRANT_COLLECTION_PREFIX = os.getenv("QDRANT_COLLECTION_PREFIX")


def _model_is_cached(model_name: str) -> bool:
    cache_root = os.environ.get(
        "HF_HUB_CACHE",
        Path.home() / ".cache" / "huggingface" / "hub",
    )

    repo_dir = Path(cache_root) / (
        "models--" + model_name.replace("/", "--")
    )

    return repo_dir.is_dir()


if EMBEDDING_MODEL and _model_is_cached(EMBEDDING_MODEL):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"