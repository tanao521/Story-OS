from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_json(path: str, data: dict[str, Any]) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: str) -> dict[str, Any]:
    target_path = Path(path)
    return json.loads(target_path.read_text(encoding="utf-8"))


def save_markdown(path: str, content: str) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
