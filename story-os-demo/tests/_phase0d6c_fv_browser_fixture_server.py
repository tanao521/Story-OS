"""Isolated browser fixture for Phase 0D6-C-FV.

The fixture uses the real FastAPI app and sealed 0D6-B services, but keeps all
state below a temporary workspace.  The ASGI wrapper only audits progression
requests and can drop one successful start response after the durable service
has completed, which lets the browser exercise idempotent replay.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))


def seed_project(project_root: Path) -> None:
    from core.project_context import get_project_context
    from system.chapter_lifecycle_service import ChapterLifecycleService
    from system.narrative_branch_lifecycle_service import BranchLifecycleService

    project_root.mkdir(parents=True, exist_ok=True)
    ctx = get_project_context(project_root)
    data = ctx.data_dir
    for directory in (
        data / "chapters", data / "versions", data / "canon_versions",
        data / "audit", data / "branch_operations",
        data / "chapter_lifecycle" / "operations",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text(json.dumps({
        "schema_version": "1.0", "project_id": project_root.name,
        "slug": project_root.name, "title": "0D6-C-FV isolated project",
        "genre": "fixture", "project_root": "projects/0d6c-fv-project",
    }), encoding="utf-8")
    (data / "story_spec.json").write_text(json.dumps({
        "schema_version": "1.0", "title": "0D6-C-FV isolated project",
        "genre": "fixture", "length": "short",
    }), encoding="utf-8")
    (data / "state.json").write_text(json.dumps({
        "schema_version": "1.0", "project_id": project_root.name,
        "timeline_id": "main", "current_chapter": 1, "status": "drafting",
    }), encoding="utf-8")
    (data / "derived_state.json").write_text("{}", encoding="utf-8")
    (data / "next_chapter_plan.json").write_text(
        json.dumps({"chapter_id": 2, "revision": "plan-2"}), encoding="utf-8")
    (data / "chapters" / "chapter_001.md").write_text(
        "# Chapter 001\n\nThe fixture chapter is durably committed.", encoding="utf-8")
    commits = data / "chapter_commits"
    commits.mkdir(exist_ok=True)
    (commits / "commit_001.json").write_text(json.dumps({
        "schema_version": "1.0", "commit_id": "commit-001",
        "chapter_id": 1, "status": "committed",
        "source_version_id": "source-001", "canon_revision_id": "canon-001",
    }), encoding="utf-8")

    from core.project_context import get_project_context
    context = get_project_context(project_root)
    scope = {"project_id": project_root.name, "timeline_id": "main"}
    branches = BranchLifecycleService(context)
    branches.create("branch-create", {**scope, "branch_id": "main"})
    revision = branches.list_branches(**scope)["registry_revision"]
    branches.select("branch-select", {
        **scope, "branch_id": "main", "expected_registry_revision": revision,
    })
    ChapterLifecycleService(context).create_next_chapter(operation_id="chapter-create")

    # Narrative Turn context inputs used after the successor rebind.  They are
    # deterministic fixture records, never provider-backed or user data.
    (data / "story_planning.json").write_text(json.dumps({
        "schema_version": "1.0", "chapters": [{
            "chapter_id": 2, "chapter_number": 2, "title": "FV successor",
            "goal": "Load the initial Turn", "conflicts": [], "plot_threads": [],
            "dependencies": [], "active_conflicts": [], "resources": {},
            "world_rules": [], "characters_present": ["fixture"], "locations": [],
        }],
    }), encoding="utf-8")
    (data / "world_bible.json").write_text(json.dumps({
        "schema_version": "1.0", "core_rules": [], "taboos_or_limits": [],
        "locations": [], "factions": [], "items": [],
    }), encoding="utf-8")
    (data / "characters.json").write_text(json.dumps({
        "schema_version": "1.0", "main_characters": [{"id": "fixture", "name": "Fixture", "role": "protagonist"}],
        "supporting_characters": [],
    }), encoding="utf-8")
    planning_control = data / "planning_control"
    planning_control.mkdir(parents=True, exist_ok=True)
    (planning_control / "rolling_window.json").write_text(json.dumps({
        "schema_version": "1.0", "current_chapter": 2, "remaining_chapters": 2, "window_size": 3,
    }), encoding="utf-8")
    (planning_control / "dependencies.json").write_text(json.dumps({
        "schema_version": "1.0", "blocking_dependencies": [],
    }), encoding="utf-8")
    from system.narrative_turn_context import branch_state_content_revision
    branch_state = {
        "schema_version": "1.0", "project_id": project_root.name,
        "timeline_id": "main", "branch_id": "main", "chapter": 2,
        "time_of_day": "morning", "last_turn_id": None, "last_event_sequence": 0,
        "last_result_fingerprint": None, "applied_result_fingerprints": [],
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    branch_state["revision"] = branch_state_content_revision(branch_state)
    state_path = ctx.narrative_state_dir / "main" / "main" / "current.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(branch_state), encoding="utf-8")


def setup_workspace(root: Path) -> dict[str, Any]:
    projects = root / "projects"
    project = projects / "0d6c-fv-project"
    seed_project(project)
    config = root / ".story_os"
    config.mkdir(parents=True, exist_ok=True)
    (config / "config.json").write_text(json.dumps({
        "active_project": "projects/0d6c-fv-project",
        "web": {"host": "127.0.0.1", "port": 7863, "open_browser": False},
    }), encoding="utf-8")
    (config / "projects.json").write_text(json.dumps({
        "schema_version": "1.0", "projects": [{
            "project_id": "0d6c-fv-project", "project_root": "projects/0d6c-fv-project",
            "title": "0D6-C-FV isolated project",
        }],
    }), encoding="utf-8")
    return {"workspace": root, "project": project, "project_id": project.name}


class ProgressionAuditMiddleware:
    """Audit only; never changes production route behavior except optional drop/delay."""

    def __init__(self, downstream, audit_path: Path):
        self.downstream = downstream
        self.audit_path = audit_path
        self.records: list[dict[str, Any]] = []
        self.drop_remaining = os.environ.get("STORYOS_FV_DROP_START_RESPONSE") == "1"
        self.delay = float(os.environ.get("STORYOS_FV_START_DELAY", "0") or 0)
        # RC4 needs deterministic transport races for both authority reads and
        # mutations.  These controls are test-fixture-only and delay a response
        # only after the real route/service has produced it.
        self.readiness_delay = float(os.environ.get("STORYOS_RC4_READINESS_DELAY", "0") or 0)

    def _save(self) -> None:
        self.audit_path.write_text(json.dumps({"requests": self.records}, indent=2), encoding="utf-8")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in {
            "/api/chapter-progression/readiness", "/api/chapter-progression/start-turn",
        }:
            await self.downstream(scope, receive, send)
            return
        body = b""
        async def audit_receive():
            nonlocal body
            message = await receive()
            body += message.get("body", b"")
            return message
        record: dict[str, Any] = {
            "method": scope.get("method"), "path": scope.get("path"),
            "body": None, "status": None, "dropped": False,
        }
        messages: list[dict[str, Any]] = []
        async def capture(message):
            messages.append(message)
        await self.downstream(scope, audit_receive, capture)
        if body:
            try:
                record["body"] = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                record["body"] = "<unreadable>"
        for message in messages:
            if message.get("type") == "http.response.start":
                record["status"] = message.get("status")
        if scope.get("path") == "/api/chapter-progression/start-turn" and self.delay:
            await asyncio.sleep(self.delay)
        if scope.get("path") == "/api/chapter-progression/readiness" and self.readiness_delay:
            await asyncio.sleep(self.readiness_delay)
        drop = (
            self.drop_remaining and scope.get("path") == "/api/chapter-progression/start-turn"
            and record.get("status") == 200
        )
        if drop:
            self.drop_remaining = False
            record["dropped"] = True
        self.records.append(record)
        self._save()
        if drop:
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        for message in messages:
            await send(message)


def main() -> None:
    import uvicorn
    from web.app import app

    workspace = Path(tempfile.mkdtemp(prefix="phase0d6c_fv_browser_"))
    info = setup_workspace(workspace)
    os.chdir(workspace)
    audit_path = info["project"] / ".fv_network_audit.json"
    app.add_middleware(ProgressionAuditMiddleware, audit_path=audit_path)
    print(json.dumps({
        "workspace": str(workspace), "project": str(info["project"]),
        "project_id": info["project_id"], "url":
        "http://127.0.0.1:7863/?mode=simulator&view=narrative-turn&project_id=0d6c-fv-project&timeline_id=main&branch_id=main&chapter_id=1",
        "audit": str(audit_path),
    }), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=7863, log_level="warning")


if __name__ == "__main__":
    main()
