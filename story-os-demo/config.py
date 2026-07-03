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


load_dotenv()

DATA_DIR = Path("data")
CONFIG_DIR = Path(".story_os")
LOCAL_CONFIG_PATH = CONFIG_DIR / "config.json"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
USE_DEEPSEEK_FOR_EDITING = _env_bool("USE_DEEPSEEK_FOR_EDITING", False)

LOCAL_MODEL_API_KEY = os.getenv("LOCAL_MODEL_API_KEY", "")
LOCAL_MODEL_BASE_URL = os.getenv("LOCAL_MODEL_BASE_URL", "")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "")
USE_LOCAL_MODEL_FOR_DRAFT = _env_bool("USE_LOCAL_MODEL_FOR_DRAFT", False)

USE_DEEPSEEK_FOR_QUALITY_CHECK = _env_bool("USE_DEEPSEEK_FOR_QUALITY_CHECK", False)

USE_DEEPSEEK_FOR_QA = _env_bool("USE_DEEPSEEK_FOR_QA", False)
