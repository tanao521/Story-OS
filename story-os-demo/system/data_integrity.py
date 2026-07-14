"""Non-destructive project data validation and reference checks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext, get_project_context

CORE_JSON = {"story_spec.json": ("title",), "story_blueprint.json": (), "characters.json": (), "world_bible.json": (), "state.json": ("current_chapter",)}


class DataIntegrityChecker:
    def __init__(self, context: ProjectContext | None = None) -> None: self.context = context or get_project_context()

    def check(self) -> dict[str, Any]:
        checks=[]; issues=[]
        for name, required in CORE_JSON.items():
            path=self.context.data_dir / name
            item={"name": name, "status": "ok", "code": ""}
            if not path.exists(): item.update({"status":"warning","code":"DATA_FILE_MISSING","message":f"Required project file is missing: {name}"})
            else:
                try: value=json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError): item.update({"status":"error","code":"DATA_JSON_INVALID","message":f"JSON file is unreadable: {name}"})
                else:
                    if not isinstance(value, dict): item.update({"status":"error","code":"DATA_SCHEMA_INVALID","message":f"JSON root must be an object: {name}"})
                    elif any(key not in value for key in required): item.update({"status":"warning","code":"DATA_FIELD_MISSING","message":f"Required fields are missing: {name}"})
            checks.append(item)
            if item["status"] != "ok": issues.append(item)
        for directory in (self.context.chapters_dir, self.context.versions_dir, self.context.memory_dir, self.context.model_runs_dir):
            checks.append({"name": self.context.relative_path(directory), "status":"ok" if directory.exists() else "warning", "code":"" if directory.exists() else "DATA_DIRECTORY_MISSING"})
        status="unhealthy" if any(item["status"]=="error" for item in checks) else ("warning" if issues else "healthy")
        return {"status":status,"checks":checks,"issues":issues}
