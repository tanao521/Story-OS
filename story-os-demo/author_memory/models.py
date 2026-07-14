"""Small serializable contracts for author knowledge assets."""
from __future__ import annotations

from typing import Any, TypedDict


class AuthorAsset(TypedDict, total=False):
    id: str
    type: str
    name: str
    category: str
    content: str
    tags: list[str]
    created_at: str
    updated_at: str
    source: str
    data: dict[str, Any]
