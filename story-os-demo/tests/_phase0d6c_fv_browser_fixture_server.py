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


def seed_project(project_root: Path, canonical_project_id: str, *, sibling: bool) -> None:
    from core.project_context import get_project_context
    from system.chapter_lifecycle_service import ChapterLifecycleService
    from system.narrative_branch_lifecycle_service import BranchLifecycleService

    ctx = get_project_context(project_root)
    data = ctx.data_dir
    for directory in (
        data / "chapters", data / "versions", data / "canon_versions",
        data / "audit", data / "branch_operations",
        data / "chapter_lifecycle" / "operations",
    ):
        directory.mkdir(parents=True, exist_ok=True)
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
    drafts = data / "drafts"
    drafts.mkdir(exist_ok=True)
    successor_text = "# Chapter 002\n\nThe successor Turn has been durably confirmed in the isolated fixture."
    (drafts / "chapter_002_draft_v001.json").write_text(json.dumps({
        "chapter_id": 2,
        "version_label": "draft_v001",
        "draft_text": successor_text,
        "actual_word_count": len(successor_text),
        "generation": {"mode": "fixture", "fallback_used": True},
    }), encoding="utf-8")
    (drafts / "chapter_002_draft_v001.md").write_text(successor_text, encoding="utf-8")
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
    scope = {"project_id": canonical_project_id, "timeline_id": "main"}
    branches = BranchLifecycleService(
        context, canonical_project_id=canonical_project_id
    )
    branches.create("branch-create", {**scope, "branch_id": "main"})
    if sibling:
        branches.create(
            "branch-create-sibling",
            {**scope, "branch_id": "sibling", "display_name": "Sibling"},
        )
    revision = branches.list_branches(**scope)["registry_revision"]
    branches.select("branch-select", {
        **scope, "branch_id": "main", "expected_registry_revision": revision,
    })
    # The formal browser completion flow consumes the real simulator read model,
    # which requires an existing branch-scoped vector manifest before Compile.
    # This is fixture-only authority data; it does not create or modify a
    # production vector index.
    manifest_dir = data / "chroma" / "manifests" / "main"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for branch_id in ("main", "sibling") if sibling else ("main",):
        (manifest_dir / f"{branch_id}.json").write_text(json.dumps({
            "schema_version": 2,
            "project_id": canonical_project_id,
            "timeline_id": "main",
            "branch_id": branch_id,
            "vector_ready": True,
            "branch_lifecycle_status": "open",
            "canon_revision_id": "canon-001",
            "collection_name": f"fixture_{branch_id}",
        }), encoding="utf-8")
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
    from system.project_manager import ProjectManager

    manager = ProjectManager(root)
    payload = {
        "genre": "fixture", "premise": "RC11 browser fixture",
        "protagonist": "Fixture", "goal": "Verify isolation",
        "conflict": "Delayed transport", "tone": "precise",
        "target_words": 1000, "chapter_count": 2,
    }
    project_a = manager.create_project({**payload, "title": "RC11 Project A"})
    project_b = manager.create_project({**payload, "title": "RC11 Project B"})
    root_a = root / project_a["project_root"]
    root_b = root / project_b["project_root"]
    seed_project(root_a, project_a["project_id"], sibling=True)
    seed_project(root_b, project_b["project_id"], sibling=False)
    manager.activate_project(project_a["project_id"])
    return {
        "workspace": root,
        "project": root_a,
        "project_id": project_a["project_id"],
        "project_a": project_a,
        "project_b": project_b,
    }


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
        self.readiness_delay_remaining = 1

    def _save(self) -> None:
        self.audit_path.write_text(json.dumps({"requests": self.records}, indent=2), encoding="utf-8")

    async def __call__(self, scope, receive, send):
        audited_paths = {
            "/api/chapter-progression/readiness", "/api/chapter-progression/start-turn",
            "/api/narrative-chapter/compile", "/api/narrative-chapter/commit",
        }
        if scope.get("type") != "http" or scope.get("path") not in audited_paths:
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
            "query_string": scope.get("query_string", b"").decode("utf-8", "replace"),
            "body": None, "status": None, "dropped": False,
            "request_received_monotonic": asyncio.get_running_loop().time(),
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
            if message.get("type") == "http.response.body" and message.get("body"):
                try:
                    response_body = json.loads(message["body"].decode("utf-8"))
                    if isinstance(response_body, dict) and isinstance(response_body.get("error"), dict):
                        record["error_code"] = response_body["error"].get("code")
                        record["error_message"] = response_body["error"].get("message")
                    result = response_body.get("result") if isinstance(response_body, dict) else None
                    if isinstance(result, dict):
                        for key in ("turn_id", "candidate_id", "candidate_version_id", "commit_id", "status"):
                            if result.get(key) is not None:
                                record[key] = result[key]
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
        record["durable_effect_monotonic"] = asyncio.get_running_loop().time()
        self.records.append(record)
        self._save()
        if scope.get("path") == "/api/chapter-progression/start-turn" and self.delay:
            await asyncio.sleep(self.delay)
        if scope.get("path") == "/api/chapter-progression/readiness" and self.readiness_delay and self.readiness_delay_remaining:
            await asyncio.sleep(self.readiness_delay)
            self.readiness_delay_remaining = 0
        drop = (
            self.drop_remaining and scope.get("path") == "/api/chapter-progression/start-turn"
            and record.get("status") == 200
        )
        if drop:
            self.drop_remaining = False
            record["dropped"] = True
        record["response_released_monotonic"] = asyncio.get_running_loop().time()
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
    port = int(os.environ.get("STORYOS_FV_PORT", "7863"))
    print(json.dumps({
        "workspace": str(workspace), "project": str(info["project"]),
        "project_id": info["project_id"],
        "project_a": info["project_a"], "project_b": info["project_b"], "url":
        f"http://127.0.0.1:{port}/?mode=simulator&view=narrative-turn&project_id={info['project_id']}&timeline_id=main&branch_id=main&chapter_id=1",
        "audit": str(audit_path),
    }), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
