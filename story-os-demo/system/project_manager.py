"""Multi-project discovery, registration, creation and activation."""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import get_project_context
from core.setup_wizard import build_story_spec_from_answers, create_story_project
from system.data_store import DataStore


LEGACY_ID = "legacy-root-project"
SCHEMA_VERSION = "1.0"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class ProjectManagerError(RuntimeError):
    """Project-center operation failed without changing unrelated projects."""


class ProjectNotFound(ProjectManagerError):
    """The requested stable project identifier is unknown."""


class ProjectManager:
    """Non-cached request-scoped manager for a Story OS workspace."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.root = Path(workspace_root or Path.cwd()).expanduser().resolve()
        self.store = DataStore(get_project_context(self.root))
        self.projects_dir = self.root / "projects"
        self.registry_path = self.root / ".story_os" / "projects.json"
        self.config_path = self.root / ".story_os" / "config.json"

    def list_projects(self) -> dict[str, Any]:
        """Return discovered, registered, and legacy project summaries."""
        warnings: list[str] = []
        records: dict[str, dict[str, Any]] = {}
        for item in self._registry(warnings).get("projects", []):
            if isinstance(item, dict) and item.get("project_id"):
                records[str(item["project_id"])] = dict(item)
        for item in self._discover(warnings):
            project_id = str(item["project_id"])
            if project_id in records and records[project_id].get("project_root") != item.get("project_root"):
                warnings.append(f"Duplicate project id: {project_id}")
            else:
                records[project_id] = {**records.get(project_id, {}), **item}
        legacy = self._legacy(warnings)
        if legacy:
            records[LEGACY_ID] = legacy
        active_path = self._active_path(warnings)
        projects = [self._summary(record, active_path) for record in records.values()]
        projects.sort(key=lambda item: (not item["active"], item["title"].casefold(), item["project_id"]))
        return {
            "projects": projects,
            "active_project_id": next((item["project_id"] for item in projects if item["active"]), ""),
            "warnings": warnings,
        }

    def get_project(self, project_id: str) -> dict[str, Any]:
        for project in self.list_projects()["projects"]:
            if project["project_id"] == project_id:
                return project
        raise ProjectNotFound(f"Project not found: {project_id}")

    def get_active_project(self) -> dict[str, Any] | None:
        return next((project for project in self.list_projects()["projects"] if project["active"]), None)

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create one isolated project, then register and activate it."""
        spec = build_story_spec_from_answers(payload)
        slug = self._unique_slug(self._slugify(spec["title"]))
        project_root = self.projects_dir / slug
        if project_root.exists():
            raise ProjectManagerError(f"Project directory exists: projects/{slug}")
        old_active = self._active_path([])
        try:
            project_root.mkdir(parents=True, exist_ok=False)
            metadata = self._metadata(spec, project_root, slug)
            DataStore(get_project_context(project_root)).write_json(project_root / "project.json", metadata)
            create_story_project(payload, str(project_root / "data"))
            self._register(metadata)
            self._set_active(metadata["project_root"])
        except Exception as exc:
            if old_active:
                try:
                    self._set_active(old_active)
                except ProjectManagerError:
                    pass
            raise ProjectManagerError(f"Project creation failed: {exc}") from exc
        return self.get_project(str(metadata["project_id"]))

    def activate_project(self, project_id: str) -> dict[str, Any]:
        """Atomically select a valid project; invalid projects leave active unchanged."""
        project = self.get_project(project_id)
        if not project["valid"]:
            raise ProjectManagerError("Project path is invalid or initialization is incomplete.")
        self._set_active(str(project["project_root"]))
        return self.get_project(project_id)

    def _registry(self, warnings: list[str]) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"schema_version": SCHEMA_VERSION, "projects": []}
        value = self.store.read_json(self.registry_path, default=None, expected_type=dict)
        if value is None:
            warnings.append("Project registry is unreadable; it was not changed.")
            return {"schema_version": SCHEMA_VERSION, "projects": []}
        if not isinstance(value.get("projects"), list):
            warnings.append("Project registry has an invalid projects list.")
            value["projects"] = []
        return value

    def _register(self, metadata: dict[str, Any]) -> None:
        warnings: list[str] = []
        registry = self._registry(warnings)
        if warnings and self.registry_path.exists():
            raise ProjectManagerError("Cannot update an unreadable project registry.")
        entries = [entry for entry in registry["projects"] if entry.get("project_id") != metadata["project_id"]]
        entries.append({key: metadata[key] for key in ("project_id", "slug", "title", "genre", "project_root", "created_at", "updated_at")})
        registry.update({"schema_version": SCHEMA_VERSION, "projects": entries})
        self.store.write_json(self.registry_path, registry, backup=True)

    def _active_path(self, warnings: list[str]) -> str:
        if not self.config_path.exists():
            return ""
        config = self.store.read_json(self.config_path, default=None, expected_type=dict)
        if config is None:
            warnings.append("Active-project configuration is unreadable.")
            return ""
        return str(config.get("active_project") or "").strip()

    def _set_active(self, project_root: str) -> None:
        config: dict[str, Any] = {}
        if self.config_path.exists():
            config = self.store.read_json(self.config_path, default=None, expected_type=dict)
            if config is None:
                raise ProjectManagerError("Cannot update unreadable active-project configuration.")
        config["active_project"] = project_root
        self.store.write_json(self.config_path, config, backup=True)

    def _discover(self, warnings: list[str]) -> list[dict[str, Any]]:
        if not self.projects_dir.exists():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(self.projects_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_dir():
                continue
            manifest = path / "project.json"
            value = self.store.read_json(manifest, default=None, expected_type=dict)
            if value is None or not value.get("project_id"):
                warnings.append(f"Invalid project metadata: projects/{path.name}")
                continue
            found.append({**value, "project_id": str(value["project_id"]), "project_root": self._relative(path), "legacy": False})
        return found

    def _legacy(self, warnings: list[str]) -> dict[str, Any] | None:
        spec_path = self.root / "data" / "story_spec.json"
        if not spec_path.exists():
            return None
        spec = self.store.read_json(spec_path, default={}, expected_type=dict)
        if not spec:
            warnings.append("Legacy project story_spec.json is unreadable.")
        return {
            "project_id": LEGACY_ID, "slug": "legacy-root", "title": str(spec.get("title") or "Legacy local project"),
            "genre": str(spec.get("genre") or ""), "project_root": ".", "created_at": "", "updated_at": "", "legacy": True,
        }

    def _summary(self, record: dict[str, Any], active_path: str) -> dict[str, Any]:
        path = self._resolve(str(record.get("project_root") or ""))
        warnings: list[str] = []
        valid = bool(path and path.is_dir())
        spec: dict[str, Any] = {}
        state: dict[str, Any] = {}
        if not valid:
            warnings.append("Project path is invalid.")
        else:
            local = DataStore(get_project_context(path))
            spec = local.read_json(path / "data" / "story_spec.json", default={}, expected_type=dict) or {}
            state = local.read_json(path / "data" / "state.json", default={}, expected_type=dict) or {}
            if not (path / "data" / "story_spec.json").exists() or not (path / "data" / "state.json").exists():
                valid = False
                warnings.append("Project initialization is incomplete.")
        chapter = int(state.get("current_chapter", 0) or 0) if state else None
        return {
            "project_id": str(record["project_id"]), "slug": str(record.get("slug") or ""), "title": str(spec.get("title") or record.get("title") or "Untitled project"),
            "genre": str(spec.get("genre") or record.get("genre") or ""), "project_root": str(record.get("project_root") or ""),
            "current_chapter": chapter, "next_chapter": chapter + 1 if chapter is not None else None,
            "current_stage": str(state.get("current_stage") or "unknown"), "created_at": str(record.get("created_at") or ""),
            "updated_at": str(record.get("updated_at") or ""), "active": str(record.get("project_root") or "") == active_path,
            "legacy": bool(record.get("legacy", False)), "valid": valid, "warnings": warnings,
        }

    def _metadata(self, spec: dict[str, Any], path: Path, slug: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {"schema_version": SCHEMA_VERSION, "project_id": uuid.uuid4().hex, "slug": slug, "title": spec["title"],
                "genre": spec["genre"], "project_root": self._relative(path), "created_at": now, "updated_at": now}

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix() or "."

    def _resolve(self, value: str) -> Path | None:
        candidate = self.root if value == "." else (self.root / value).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate

    def _unique_slug(self, base: str) -> str:
        candidate, index = base, 2
        while (self.projects_dir / candidate).exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    @staticmethod
    def _slugify(title: str) -> str:
        value = _INVALID.sub("-", unicodedata.normalize("NFKC", title).strip())
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[-.]+", "-", value).strip("-._")[:72].strip("-._")
        return "novel-project" if not value or value.casefold() in _RESERVED else value


def get_project_manager(workspace_root: str | Path | None = None) -> ProjectManager:
    """Return a new manager so project switches never leave stale state."""
    return ProjectManager(workspace_root)

