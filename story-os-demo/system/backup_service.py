"""Project-local snapshots and safe restore for core structured project data."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.errors import StorageError
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore

BACKUP_FILES=("data/story_spec.json","data/story_blueprint.json","data/characters.json","data/world_bible.json","data/state.json","data/next_chapter_plan.json","data/narrative_memory/state/current.json","data/model_preferences.json")


class BackupService:
    def __init__(self, context: ProjectContext | None = None) -> None: self.context=context or get_project_context(); self.store=DataStore(self.context)
    @property
    def root(self) -> Path: return self.context.root / "backups" / self.context.root.name
    def create(self, reason: str="manual") -> dict[str, Any]:
        backup_id=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"); target=self.root/backup_id; files=[]
        for relative in BACKUP_FILES:
            source=self.context.root/relative
            if not source.exists() or not source.is_file(): continue
            content=source.read_text(encoding="utf-8"); destination=target/relative
            self.store.write_text(destination, content, backup=False)
            files.append({"path":relative,"sha256":hashlib.sha256(content.encode("utf-8")).hexdigest()})
        if not files: raise StorageError("No project data was available to back up.", code="DATA_BACKUP_EMPTY", recoverable=True)
        manifest={"schema_version":"1.0","backup_id":backup_id,"project_id":self.context.root.name,"created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"reason":reason[:200],"files":files}
        self.store.write_json(target/"manifest.json",manifest,backup=False); self._prune(); return manifest
    def list(self, limit:int=20)->list[dict[str,Any]]:
        if not self.root.exists(): return []
        values=[]
        for path in self.root.iterdir():
            item=self.store.read_json(path/"manifest.json",default=None,expected_type=dict) if path.is_dir() else None
            if item: values.append(item)
        return sorted(values,key=lambda item:str(item.get("created_at","")),reverse=True)[:max(1,min(limit,50))]
    def restore(self, backup_id:str, *, files:list[str]|None=None)->dict[str,Any]:
        manifest=self.store.read_json(self.root/backup_id/"manifest.json",default=None,expected_type=dict)
        if not manifest: raise StorageError("Backup was not found or is unreadable.",code="DATA_BACKUP_NOT_FOUND",recoverable=True)
        current=self.create("before_restore")
        allowed={item["path"] for item in manifest.get("files",[]) if isinstance(item,dict) and item.get("path")}
        selected=allowed if files is None else allowed & {str(item) for item in files}
        restored=[]
        for relative in selected:
            source=self.root/backup_id/relative
            if not source.exists(): continue
            content=source.read_text(encoding="utf-8"); self.store.write_text(relative,content,backup=True); restored.append(relative)
        return {"backup_id":backup_id,"restored":sorted(restored),"safety_backup_id":current["backup_id"]}
    def _prune(self)->None:
        for item in self.list(limit=200)[10:]:
            # Retention only removes complete automatic snapshots, never the latest ten.
            if str(item.get("reason","")) != "automatic": continue
            path=self.root/str(item.get("backup_id",""))
            if path.exists():
                import shutil; shutil.rmtree(path,ignore_errors=True)
