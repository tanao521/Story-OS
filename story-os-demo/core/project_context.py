"""Resolve the active Story OS project without process-wide path state."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


class ProjectContextError(RuntimeError):
    """Raised when a Story OS project cannot be resolved safely."""


class ProjectNotFoundError(ProjectContextError):
    """Raised when the selected project directory is unavailable."""


class ProjectConfigError(ProjectContextError):
    """Raised when the active-project configuration is invalid."""


class InvalidProjectPathError(ProjectContextError):
    """Raised when a selected project path is not a directory."""


@dataclass(frozen=True)
class ProjectContext:
    """Normalized, authoritative paths for one project operation."""

    root: Path
    data_dir: Path
    chapters_dir: Path
    drafts_dir: Path
    edited_dir: Path
    manual_dir: Path
    versions_dir: Path
    summaries_dir: Path
    quality_reports_dir: Path
    continuity_reports_dir: Path
    reviews_dir: Path
    todos_dir: Path
    context_dir: Path
    memory_dir: Path
    pipeline_runs_dir: Path
    jobs_dir: Path
    archive_dir: Path
    logs_dir: Path
    config_dir: Path
    legacy_chapters_dir: Path
    narrative_memory_dir: Path
    narrative_events_dir: Path
    narrative_state_dir: Path
    narrative_snapshots_dir: Path
    model_runs_dir: Path
    model_preferences_path: Path
    model_cost_limits_path: Path
    agents_dir: Path
    agent_runs_dir: Path
    agent_workflows_dir: Path
    creative_loop_dir: Path
    reflections_dir: Path
    creative_health_dir: Path
    creative_issues_dir: Path
    creative_proposals_dir: Path
    creative_experiments_dir: Path
    creative_patterns_dir: Path
    creative_evolution_dir: Path
    creative_outcomes_dir: Path
    creative_events_dir: Path
    creative_audit_dir: Path
    planning_control_dir: Path
    planning_strategy_path: Path
    planning_milestones_path: Path
    volume_contracts_path: Path
    phase_contracts_path: Path
    planning_locks_path: Path
    planning_conflicts_path: Path
    planning_metadata_path: Path
    planning_control_versions_dir: Path
    rolling_window_path: Path
    planning_dependencies_path: Path

    def relative_path(self, path: Path) -> str:
        """Return a safe project-relative display path."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()


def get_project_context(project_root: str | Path | None = None) -> ProjectContext:
    """Resolve explicit root, configured active project, then the current directory."""
    bound = _operation_context.get()
    if project_root is None and bound is not None:
        return bound
    cwd = Path.cwd().expanduser().resolve()
    root = _resolve_root(project_root, cwd)
    if not root.exists():
        raise ProjectNotFoundError(f"Project root does not exist: {root}")
    if not root.is_dir():
        raise InvalidProjectPathError(f"Project root is not a directory: {root}")
    data = root / "data"
    return ProjectContext(
        root=root, data_dir=data, chapters_dir=data / "chapters", drafts_dir=data / "drafts",
        edited_dir=data / "edited", manual_dir=data / "manual", versions_dir=data / "versions",
        summaries_dir=data / "summaries", quality_reports_dir=data / "quality_reports",
        continuity_reports_dir=data / "continuity_reports", reviews_dir=data / "reviews",
        todos_dir=data / "todos", context_dir=data / "context", memory_dir=data / "memory",
        pipeline_runs_dir=data / "pipeline_runs", jobs_dir=data / "jobs", archive_dir=data / "archive",
        logs_dir=root / "logs", config_dir=root / ".story_os", legacy_chapters_dir=root / "chapters",
        narrative_memory_dir=data / "narrative_memory", narrative_events_dir=data / "narrative_memory" / "events", narrative_state_dir=data / "narrative_memory" / "state", narrative_snapshots_dir=data / "narrative_memory" / "snapshots",
        model_runs_dir=data / "model_runs", model_preferences_path=data / "model_preferences.json",
        model_cost_limits_path=data / "model_cost_limits.json",
        agents_dir=data / "agents", agent_runs_dir=data / "agents" / "runs",
        agent_workflows_dir=data / "agents" / "workflows",
        creative_loop_dir=data / "creative_loop", reflections_dir=data / "creative_loop" / "reflections",
        creative_health_dir=data / "creative_loop" / "health", creative_issues_dir=data / "creative_loop" / "issues",
        creative_proposals_dir=data / "creative_loop" / "proposals", creative_experiments_dir=data / "creative_loop" / "experiments",
        creative_patterns_dir=data / "creative_loop" / "patterns", creative_evolution_dir=data / "creative_loop" / "evolution",
        creative_outcomes_dir=data / "creative_loop" / "outcomes", creative_events_dir=data / "creative_loop" / "events",
        creative_audit_dir=data / "creative_loop" / "audit",
        planning_control_dir=data / "planning_control",
        planning_strategy_path=data / "planning_control" / "strategy.json",
        planning_milestones_path=data / "planning_control" / "milestones.json",
        volume_contracts_path=data / "planning_control" / "volume_contracts.json",
        phase_contracts_path=data / "planning_control" / "phase_contracts.json",
        planning_locks_path=data / "planning_control" / "locks.json",
        planning_conflicts_path=data / "planning_control" / "conflicts.json",
        planning_metadata_path=data / "planning_control" / "metadata.json",
        planning_control_versions_dir=data / "planning_control" / "versions",
        rolling_window_path=data / "planning_control" / "rolling_window.json",
        planning_dependencies_path=data / "planning_control" / "dependencies.json",
    )


_operation_context: ContextVar[ProjectContext | None] = ContextVar(
    "story_os_operation_context", default=None
)


@contextmanager
def bind_project_context(context: ProjectContext):
    """Bind one immutable project context to the current operation thread."""
    token = _operation_context.set(context)
    try:
        yield context
    finally:
        _operation_context.reset(token)


def _resolve_root(value: str | Path | None, cwd: Path) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    config_path = cwd / ".story_os" / "config.json"
    if not config_path.exists():
        return cwd
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectConfigError(
            f"Cannot read active-project configuration: {config_path} (the file was not changed)"
        ) from exc
    if not isinstance(config, dict):
        raise ProjectConfigError(f"Active-project configuration must be a JSON object: {config_path}")
    active = config.get("active_project")
    if active in (None, ""):
        return cwd
    if not isinstance(active, str):
        raise ProjectConfigError(f"active_project must be a path string: {config_path}")
    candidate = Path(active).expanduser()
    root = (cwd / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not root.exists() or not root.is_dir():
        raise ProjectNotFoundError(f"Configured active_project is not an accessible directory: {root}")
    return root

