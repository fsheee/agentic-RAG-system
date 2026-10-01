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

# Minimum relevance score (LangChain-normalized, 0..1) for a retrieved
# chunk to be used. Calibrated on the golden set + off-topic questions:
# on-topic chunks score >= 0.70, off-topic <= 0.56.
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.65"))

# Chunks scoring more than this far below the best match are dropped even
# if they clear RETRIEVAL_THRESHOLD, so loosely-related chunks are not
# cited as sources. Genuinely multi-source answers (chunks scoring close
# together) still keep all their sources.
SCORE_MARGIN = float(os.getenv("SCORE_MARGIN", "0.10"))


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