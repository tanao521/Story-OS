"""Prompt metadata, hashes, and version identifiers without storing prompt bodies in traces."""
from __future__ import annotations

import hashlib
from typing import Any


PROMPTS = {
    "story_spec": {"version": "1.0", "label": "Story specification"},
    "story_blueprint": {"version": "1.0", "label": "Story blueprint"},
    "next_chapter_plan": {"version": "1.0", "label": "Next chapter plan"},
    "chapter_draft": {"version": "1.0", "label": "Chapter draft"},
    "edit_draft": {"version": "1.0", "label": "Draft edit"},
    "quality_review": {"version": "1.0", "label": "Quality review"},
    "continuity_review": {"version": "1.0", "label": "Continuity review"},
    "generic": {"version": "1.0", "label": "Generic model call"},
}


class PromptRegistry:
    def list(self) -> list[dict[str, str]]:
        return [{"prompt_id": key, **value} for key, value in PROMPTS.items()]

    def get(self, prompt_id: str) -> dict[str, str] | None:
        item = PROMPTS.get(prompt_id)
        return {"prompt_id": prompt_id, **item} if item else None

    def metadata(self, prompt_id: str, prompt: str) -> dict[str, str]:
        item = self.get(prompt_id) or self.get("generic") or {}
        return {"prompt_id": str(item.get("prompt_id", "generic")), "prompt_version": str(item.get("version", "1.0")), "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
