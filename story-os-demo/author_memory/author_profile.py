"""Author profile and preference priority management."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from author_memory.asset_store import AuthorAssetStore, now_iso
from core.project_context import ProjectContext


class AuthorProfileService:
    def __init__(self, context: ProjectContext) -> None: self.assets = AuthorAssetStore(context)

    def profile(self) -> dict[str, Any]:
        value = self.assets.read_profile()
        return {"id": value.get("id") or f"author_{uuid4().hex}", "name": value.get("name") or "", "writing_preferences": value.get("writing_preferences") if isinstance(value.get("writing_preferences"), dict) else {}, "favorite_genres": value.get("favorite_genres") if isinstance(value.get("favorite_genres"), list) else [], "avoid_patterns": value.get("avoid_patterns") if isinstance(value.get("avoid_patterns"), list) else [], "style_summary": value.get("style_summary") or "", "experience_level": value.get("experience_level") or "", "updated_at": value.get("updated_at") or ""}

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        profile = self.profile(); allowed = {"name", "writing_preferences", "favorite_genres", "avoid_patterns", "style_summary", "experience_level"}
        for key in allowed:
            if key in changes: profile[key] = changes[key]
        profile["updated_at"] = now_iso(); return self.assets.write_profile(profile)

    def preferences(self) -> list[dict[str, Any]]: return self.assets.list_preferences()

    def update_preferences(self, changes: dict[str, Any]) -> list[dict[str, Any]]:
        incoming = changes.get("preferences", changes.get("items", changes))
        if not isinstance(incoming, list): incoming = [incoming] if isinstance(incoming, dict) else []
        rows = self.preferences(); by_id = {str(row.get("id")): row for row in rows}
        for item in incoming:
            if not isinstance(item, dict) or not str(item.get("content", "")).strip(): continue
            row = {"id": str(item.get("id") or f"preference_{uuid4().hex}"), "type": "avoid" if item.get("type") == "avoid" else "preference", "category": str(item.get("category") or "general"), "content": str(item["content"]).strip(), "priority": "author_explicit", "updated_at": now_iso()}
            by_id[row["id"]] = row
        return self.assets.save_preferences(list(by_id.values()))
