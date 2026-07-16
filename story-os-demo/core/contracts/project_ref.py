"""Project-scoped identities used by safe write boundaries.

``ProjectRef`` is internal: it retains resolved local paths for validation.
``ProjectIdentityView`` is safe for API/audit output and intentionally exposes
only the normalized project identifier.
"""
from __future__ import annotations

import ntpath
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.project_context import ProjectContext


class ProjectRefError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_project_id(value: str) -> str:
    """Return the non-path, case-normalized identifier used outside a project."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not normalized:
        raise ProjectRefError("PROJECT_REF_INVALID", "project_id is required.")
    if len(normalized) > 128 or any(marker in normalized for marker in ("/", "\\", "\x00")):
        raise ProjectRefError("PROJECT_REF_INVALID", "project_id must be a short identifier, not a path.")
    return normalized


@dataclass(frozen=True)
class ProjectIdentityView:
    project_id: str

    def as_dict(self) -> dict[str, str]:
        return {"project_id": self.project_id}


@dataclass(frozen=True)
class ProjectRef:
    """Immutable project identity with private filesystem validation fields."""

    project_id: str
    project_root: Path
    data_root: Path

    def __post_init__(self) -> None:
        project_id = normalize_project_id(self.project_id)
        root = Path(self.project_root).expanduser().resolve()
        data_root = Path(self.data_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ProjectRefError("PROJECT_REF_INVALID", "project_root must be an existing directory.")
        try:
            data_root.relative_to(root)
        except ValueError as exc:
            raise ProjectRefError("PROJECT_REF_INVALID", "data_root must remain inside project_root.") from exc
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "data_root", data_root)

    @classmethod
    def from_context(cls, context: ProjectContext) -> "ProjectRef":
        return cls(project_id=context.root.name, project_root=context.root, data_root=context.data_dir)

    def public_view(self) -> ProjectIdentityView:
        return ProjectIdentityView(project_id=self.project_id)

    def assert_context(self, context: ProjectContext) -> None:
        candidate = ProjectRef.from_context(context)
        if candidate.project_root != self.project_root or candidate.project_id != self.project_id:
            raise ProjectRefError("PROJECT_MISMATCH", "Project reference does not match the active project.")

    def assert_project_id(self, value: str) -> None:
        """Accept the safe identifier and existing internal absolute-root form only."""
        try:
            if normalize_project_id(value) == self.project_id:
                return
        except ProjectRefError:
            pass
        try:
            if Path(str(value)).expanduser().resolve() == self.project_root:
                return
        except (OSError, ValueError):
            pass
        raise ProjectRefError("PROJECT_MISMATCH", "Operation belongs to a different project.")

    def relative_target_path(self, value: str | Path) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ProjectRefError("TARGET_PATH_REQUIRED", "A project-relative target path is required.")
        if raw.startswith(("\\\\", "//")) or ntpath.splitdrive(raw)[0] or Path(raw).is_absolute():
            raise ProjectRefError("TARGET_PATH_ABSOLUTE", "Target paths must be project-relative.")
        normalized = raw.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if ".." in parts:
            raise ProjectRefError("TARGET_PATH_TRAVERSAL", "Target paths may not traverse outside the project.")
        candidate = (self.project_root / Path(*parts)).resolve()
        try:
            relative = candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise ProjectRefError("TARGET_PATH_OUTSIDE_PROJECT", "Target path resolves outside the project.") from exc
        if relative == Path("."):
            raise ProjectRefError("TARGET_PATH_REQUIRED", "A file target path is required.")
        return relative.as_posix()
