"""Workspace-level author assets, deliberately separate from story projects."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


ASSET_CATEGORIES = {"characters", "worlds", "settings", "plots", "themes", "scenes", "ideas"}


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()


def workspace_context(context: ProjectContext) -> ProjectContext:
    """Find the Story OS workspace, not an active child project."""
    for candidate in (context.root, *context.root.parents):
        if (candidate / ".story_os").is_dir():
            return get_project_context(candidate)
    return get_project_context(context.root)


class AuthorAssetStore:
    """Only user-saved author assets live here; project manuscripts never do."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = workspace_context(context)
        self.store = DataStore(self.context)

    def profile_path(self) -> str: return "data/author_profile/profile.json"
    def preferences_path(self) -> str: return "data/author_profile/preferences.json"
    def experiences_path(self) -> str: return "data/author_profile/experiences.json"

    def read_profile(self) -> dict[str, Any]:
        return self.store.read_json(self.profile_path(), default={}, expected_type=dict) or {}

    def write_profile(self, value: dict[str, Any]) -> dict[str, Any]:
        self.store.write_json(self.profile_path(), value, backup=True); return value

    def list_preferences(self) -> list[dict[str, Any]]:
        return self.store.read_json(self.preferences_path(), default=[], expected_type=list) or []

    def save_preferences(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.store.write_json(self.preferences_path(), rows, backup=True); return rows

    def list_experiences(self) -> list[dict[str, Any]]:
        return self.store.read_json(self.experiences_path(), default=[], expected_type=list) or []

    def add_experience(self, value: dict[str, Any], kind: str) -> dict[str, Any]:
        row = {"id": f"experience_{uuid4().hex}", "type": kind, "created_at": now_iso(), **value}
        rows = self.list_experiences(); rows.append(row); self.store.write_json(self.experiences_path(), rows, backup=True); return row

    def add_asset(self, value: dict[str, Any]) -> dict[str, Any]:
        category = str(value.get("category") or "ideas").strip().lower()
        if category not in ASSET_CATEGORIES: category = "ideas"
        row = {"id": f"asset_{uuid4().hex}", "type": str(value.get("type") or "idea"), "name": str(value.get("name") or "未命名资产"),
               "category": category, "content": str(value.get("content") or ""), "tags": [str(x) for x in value.get("tags", []) if str(x).strip()] if isinstance(value.get("tags"), list) else [],
               "data": value.get("data") if isinstance(value.get("data"), dict) else {}, "source": "manual_input", "created_at": now_iso(), "updated_at": now_iso()}
        self.store.write_json(f"data/creative_assets/{category}/{row['id']}.json", row); return row

    def list_assets(self, query: str = "") -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        base = self.store.path("data/creative_assets")
        if not base.exists(): return result
        needle = query.casefold().strip()
        for category in ASSET_CATEGORIES:
            directory = base / category
            if not directory.exists(): continue
            for path in directory.glob("*.json"):
                row = self.store.read_json(path, default=None, expected_type=dict)
                if not row: continue
                haystack = " ".join([str(row.get("name", "")), str(row.get("content", "")), " ".join(map(str, row.get("tags", [])))])
                if not needle or needle in haystack.casefold(): result.append(row)
        return sorted(result, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
