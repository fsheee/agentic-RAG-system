import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "openai/gpt-oss-120b",
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)


def _model_is_cached(model_name):
    cache_root = os.environ.get(
        "HF_HUB_CACHE",
        Path.home() / ".cache" / "huggingface" / "hub",
    )

    repo_dir = Path(cache_root) / (
        "models--" + model_name.replace("/", "--")
    )

    return repo_dir.is_dir()


# Enable Hugging Face offline mode only when
# the embedding model is already cached locally.
if _model_is_cached(EMBEDDING_MODEL):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"