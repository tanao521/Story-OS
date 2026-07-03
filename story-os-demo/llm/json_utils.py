from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


def extract_json_from_text(text: str) -> dict[str, Any]:
    candidates = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        candidates.append(code_block_match.group(1).strip())

    object_match = re.search(r"\{.*\}", text, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0).strip())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def ensure_required_keys(data: dict[str, Any], required_keys: list[str]) -> list[str]:
    return [key for key in required_keys if key not in data]


def deep_merge_missing(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(patch)
    for key, value in base.items():
        if key not in merged or merged[key] in (None, ""):
            merged[key] = deepcopy(value)
            continue
        if isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = deep_merge_missing(value, merged[key])
    return merged
