"""Canonical product-project identity resolution at legacy storage boundaries."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from core.project_context import ProjectContext, get_project_context
from system.project_manager import ProjectManager, ProjectManagerError, ProjectNotFound


class ProjectIdentityResolutionError(RuntimeError):
    """Canonical identity could not be resolved without guessing."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedProjectIdentity:
    project_id: str
    storage_project_id: str
    context: ProjectContext


class ProjectIdentityResolver:
    """Map a formal registry UUID to its existing storage directory slug."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.manager = ProjectManager(workspace_root)

    def resolve(self, project_id: str) -> ResolvedProjectIdentity:
        try:
            canonical_id = uuid.UUID(str(project_id)).hex
        except (ValueError, AttributeError, TypeError) as exc:
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found") from exc
        if canonical_id != str(project_id).replace("-", "").lower():
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found")
        try:
            record = self.manager.get_registered_project(project_id)
        except ProjectNotFound as exc:
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found") from exc
        except ProjectManagerError as exc:
            raise ProjectIdentityResolutionError(
                "PROJECT_IDENTITY_UNAVAILABLE", "Project identity authority is unavailable"
            ) from exc
        root = record["project_root_path"]
        return ResolvedProjectIdentity(
            project_id=project_id,
            storage_project_id=root.name,
            context=get_project_context(root),
        )
