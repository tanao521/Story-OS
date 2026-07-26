from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.project_context import get_project_context, ProjectContext

from .obsidian_binding import BindingStatus, ObsidianBinding


class ObsidianBindingStore:
    def __init__(self, workspace_root: Path | None = None) -> None:
        if workspace_root is None:
            workspace_root = get_project_context().root.parent
        self.workspace_root = workspace_root.resolve()
        self.bindings_dir = self.workspace_root / ".story_os" / "obsidian_bindings"
        self.bindings_dir.mkdir(parents=True, exist_ok=True)

    def _binding_filename(self, project_id: str, timeline_id: str) -> Path:
        return self.bindings_dir / f"{project_id}__{timeline_id}.json"

    def load(self, project_id: str, timeline_id: str) -> ObsidianBinding | None:
        path = self._binding_filename(project_id, timeline_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ObsidianBinding.from_dict(data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def get_binding(self, project_id: str, timeline_id: str) -> ObsidianBinding | None:
        return self.load(project_id, timeline_id)

    def save(self, binding: ObsidianBinding) -> None:
        path = self._binding_filename(binding.project_id, binding.timeline_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(binding.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def delete(self, project_id: str, timeline_id: str) -> bool:
        path = self._binding_filename(project_id, timeline_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_bindings(self) -> list[ObsidianBinding]:
        bindings: list[ObsidianBinding] = []
        if not self.bindings_dir.exists():
            return bindings
        for path in self.bindings_dir.glob("*__*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                bindings.append(ObsidianBinding.from_dict(data))
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
        return bindings

    def find_by_target(self, vault_root: Path, target_relative_path: str) -> ObsidianBinding | None:
        vault_root = vault_root.resolve()
        for binding in self.list_bindings():
            if binding.vault_root == vault_root and binding.target_relative_path == target_relative_path:
                return binding
        return None

    def is_target_conflict(self, vault_root: Path, target_relative_path: str, exclude_project_id: str | None = None, exclude_timeline_id: str | None = None) -> bool:
        vault_root = vault_root.resolve()
        for binding in self.list_bindings():
            if binding.vault_root == vault_root and binding.target_relative_path == target_relative_path:
                if exclude_project_id is not None and binding.project_id == exclude_project_id:
                    if exclude_timeline_id is None:
                        continue
                    if binding.timeline_id == exclude_timeline_id:
                        continue
                return True
        return False