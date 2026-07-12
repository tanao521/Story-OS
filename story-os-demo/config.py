from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


load_dotenv()

DATA_DIR = Path("data")
CONFIG_DIR = Path(".story_os")
LOCAL_CONFIG_PATH = CONFIG_DIR / "config.json"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
USE_DEEPSEEK_FOR_EDITING = _env_bool("USE_DEEPSEEK_FOR_EDITING", False)

WRITE_MODEL_API_KEY = _env_value("WRITE_MODEL_API_KEY", "MODEL_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
WRITE_MODEL_BASE_URL = _env_value("WRITE_MODEL_BASE_URL", "MODEL_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.openai.com/v1")
WRITE_MODEL_NAME = _env_value("WRITE_MODEL_NAME", "MODEL_NAME", "OPENAI_MODEL", "DEEPSEEK_MODEL", default="gpt-4o")
WRITE_MODEL_TIMEOUT_SECONDS = int(os.getenv("WRITE_MODEL_TIMEOUT_SECONDS", os.getenv("MODEL_TIMEOUT_SECONDS", os.getenv("LLM_TIMEOUT_SECONDS", "180"))) or "180")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "api")

OLLAMA_CLOUD_BASE_URL = os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api")
OLLAMA_CLOUD_MODEL = os.getenv("OLLAMA_CLOUD_MODEL", "deepseek-v4-pro:cloud")
OLLAMA_API_KEY = _env_value("OLLAMA_API_KEY")
OLLAMA_CLOUD_API_KEY = _env_value("OLLAMA_CLOUD_API_KEY", "OLLAMA_API_KEY", default=OLLAMA_API_KEY)
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180") or "180")

LOCAL_MODEL_API_KEY = os.getenv("LOCAL_MODEL_API_KEY", "")
LOCAL_MODEL_BASE_URL = os.getenv("LOCAL_MODEL_BASE_URL", "")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "")
USE_LOCAL_MODEL_FOR_DRAFT = _env_bool("USE_LOCAL_MODEL_FOR_DRAFT", False)

USE_DEEPSEEK_FOR_QUALITY_CHECK = _env_bool("USE_DEEPSEEK_FOR_QUALITY_CHECK", False)

USE_DEEPSEEK_FOR_QA = _env_bool("USE_DEEPSEEK_FOR_QA", False)

# ── ChromaDB / vector memory ─────────────────────────────────────────────────
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma")
VECTOR_EMBEDDING_MODEL = os.getenv(
    "VECTOR_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)
VECTOR_COLLECTION_NAME = os.getenv("VECTOR_COLLECTION_NAME", "storyos_memory")
