"""Phase 0D4-C-RC2: Isolated fixture server for browser acceptance.

Creates a temporary workspace with one project containing:
- Project + Timeline
- active/open Branch (root)
- inactive Branch (alternate)
- archived Branch (old-route)
- Chapter
- Planning / World / Character data

Starts the web server pointing at this workspace.
Run: python tests/_rc2_browser_fixture_server.py
Then open http://127.0.0.1:7862/?mode=simulator&view=narrative-turn
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))


def seed_isolated_project(project_root: Path) -> None:
    """Seed a complete isolated project at project_root."""
    from core.project_context import get_project_context
    from core.contracts.narrative_turn import TimelineContext
    from system.narrative_branch_store import NarrativeBranchStore

    project_root.mkdir(parents=True, exist_ok=True)
    ctx = get_project_context(project_root)
    data_dir = ctx.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    ctx.chapters_dir.mkdir(parents=True, exist_ok=True)
    ctx.narrative_state_dir.mkdir(parents=True, exist_ok=True)

    # Project metadata
    (project_root / "project.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "project_id": project_root.name,
            "title": "RC2 测试项目",
            "author": "RC2 Fixture",
            "created_at": "2025-01-01T00:00:00+00:00",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Planning
    planning = {
        "schema_version": "1.0",
        "chapters": [
            {
                "chapter_id": "ch-001",
                "chapter_number": 1,
                "title": "第一章：启程",
                "goal": "主角离开家乡，踏上旅程",
                "conflicts": [{"id": "c1", "title": "迷雾森林的未知危险"}],
                "plot_threads": [
                    {"thread_id": "t1", "title": "失踪的旅人", "status": "active"},
                ],
                "dependencies": [],
                "active_conflicts": ["c1"],
                "resources": {"金币": {"amount": 100, "unit": "枚"}},
                "world_rules": ["魔法需要消耗精神力"],
                "characters_present": ["mc1"],
                "locations": ["迷雾森林"],
            }
        ],
    }
    (data_dir / "story_planning.json").write_text(
        json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # World
    world = {
        "schema_version": "1.0",
        "core_rules": [{"id": "r1", "rule": "魔法需要消耗精神力", "severity": "high"}],
        "taboos_or_limits": ["使用禁忌魔法"],
        "locations": [{"id": "loc1", "name": "迷雾森林", "description": "充满未知的森林"}],
        "factions": [],
        "items": [],
    }
    (data_dir / "world_bible.json").write_text(
        json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Characters
    chars = {
        "schema_version": "1.0",
        "main_characters": [
            {"id": "mc1", "name": "林远", "role": "protagonist", "capabilities": ["剑术", "基础魔法"]},
        ],
        "supporting_characters": [],
    }
    (data_dir / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Chapter content
    (ctx.chapters_dir / "chapter_001.md").write_text(
        "# 第一章：启程\n\n林远站在村口，望着远方的迷雾森林。\n", encoding="utf-8",
    )

    # Rolling window
    rolling = {
        "schema_version": "1.0",
        "current_chapter": 1,
        "remaining_chapters": 5,
        "window_size": 3,
    }
    ctx.rolling_window_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.rolling_window_path.write_text(
        json.dumps(rolling, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Dependencies
    deps = {"schema_version": "1.0", "blocking_dependencies": []}
    ctx.planning_dependencies_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.planning_dependencies_path.write_text(
        json.dumps(deps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Current narrative state
    (ctx.narrative_state_dir / "current.json").write_text(
        json.dumps({"chapter": 1, "time_of_day": "morning"}, ensure_ascii=False),
        encoding="utf-8",
    )

    # story_spec.json (required for init-state to return initialized=true)
    (data_dir / "story_spec.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "title": "RC2 测试项目",
            "genre": "玄幻",
            "length": "长篇",
            "target_word_count": 300000,
            "narrative_perspective": "第三人称有限视角",
            "protagonist_structure": "单男主",
            "romance_intensity": "轻微",
            "tone": "热血",
            "writing_style": "电影感",
            "world_style": "迷雾森林的奇幻世界",
            "plot_focus": ["成长", "冒险"],
            "forbidden_content": [],
            "ai_style_limits": [
                "减少“不是A，而是B”句式",
                "减少破折号",
                "避免总结式表达",
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # state.json (required for init-state)
    (data_dir / "state.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "project_id": project_root.name,
            "timeline_id": "tl-main",
            "current_chapter": 1,
            "status": "drafting",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Timeline + branches
    timeline_ctx = TimelineContext(project_id=project_root.name, timeline_id="tl-main")
    store = NarrativeBranchStore(ctx)

    # Create root branch (active + open)
    store.create_branch(timeline_ctx, "root", "Root Branch")
    revision = store.get_registry_revision(timeline_ctx)
    store.select_branch(timeline_ctx, "root", revision)

    # Create alternate branch (inactive + open)
    store.create_branch(timeline_ctx, "alternate", "Alternate Timeline", "root")

    # Create archived branch
    store.create_branch(timeline_ctx, "old-route", "Old Route", "root")
    revision = store.get_registry_revision(timeline_ctx)
    store.archive_branch(timeline_ctx, "old-route", revision)

    # Create state-missing branch (open + no narrative state file → unavailable)
    # Do NOT create narrative_memory/state/{timeline_id}/state-missing/current.json
    # so that _read_branch_state returns BRANCH_STATE_UNAVAILABLE.
    store.create_branch(timeline_ctx, "state-missing", "State Missing Branch", "root")

    # Authoritative ready state for RC2 browser progression.  These are
    # production-shaped fixture records, scoped to the temporary project only.
    import hashlib
    from system.narrative_turn_context import branch_state_content_revision
    ready_text = "林远在清晨走进迷雾森林，发现一枚发光的旧徽记。"
    versions_dir = ctx.data_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    manual_path = ctx.data_dir / "manual" / "chapter_001_manual_v001.json"
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    manual_path.write_text(json.dumps({
        "chapter_id": 1, "chapter_title": "第一章：启程", "version": 1,
        "version_label": "manual_v001", "manual_text": ready_text,
        "created_at": "2026-01-01T00:00:00+00:00",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (versions_dir / "chapter_001_versions.json").write_text(json.dumps({
        "version_index": "1.5", "chapter_id": 1, "selected_version_id": "manual_v001",
        "versions": [{
            "source_type": "manual", "version": 1, "version_label": "manual_v001",
            "json_path": manual_path.as_posix(),
            "version_id": "manual_v001", "chapter_id": 1, "chapter_title": "第一章：启程",
        }], "drafts": [], "edited": [], "manual": [], "selected": {
            "source_type": "manual", "version": 1, "version_label": "manual_v001", "json_path": manual_path.as_posix(),
        }
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    canon_dir = ctx.data_dir / "canon_versions" / "chapter_001"
    canon_dir.mkdir(parents=True, exist_ok=True)
    canon_path = canon_dir / "canon_v001.md"
    canon_path.write_text(ready_text, encoding="utf-8")
    canon_id = "canon_rc2_c1"
    canon_hash = hashlib.sha256(ready_text.encode("utf-8")).hexdigest()
    (canon_dir / "index.json").write_text(json.dumps({
        "schema_version": "1.0", "chapter_id": 1, "current_version_id": canon_id,
        "versions": [{"canon_version_id": canon_id, "chapter_id": 1, "version_number": 1,
                      "content_path": "data/canon_versions/chapter_001/canon_v001.md",
                      "content_hash": canon_hash, "active": True, "source": "fixture",
                      "revision_id": "revision_rc2_c1", "created_at": "2026-01-01T00:00:00+00:00",
                      "activated_at": "2026-01-01T00:00:00+00:00"}]
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    branch_state = {
        "schema_version": "1.0", "project_id": project_root.name, "timeline_id": "tl-main", "branch_id": "root",
        "chapter": 1, "time_of_day": "morning", "last_turn_id": None,
        "last_event_sequence": 0, "last_result_fingerprint": None,
        "applied_result_fingerprints": [], "updated_at": "2026-01-01T00:00:00+00:00",
    }
    branch_state["revision"] = branch_state_content_revision(branch_state)
    state_path = ctx.narrative_state_dir / "tl-main" / "root" / "current.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(branch_state, ensure_ascii=False, indent=2), encoding="utf-8")
    alternate_state = dict(branch_state, branch_id="alternate")
    alternate_state["revision"] = branch_state_content_revision(alternate_state)
    alternate_state_path = ctx.narrative_state_dir / "tl-main" / "alternate" / "current.json"
    alternate_state_path.parent.mkdir(parents=True, exist_ok=True)
    alternate_state_path.write_text(json.dumps(alternate_state, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = ctx.data_dir / "chroma" / "manifests" / "tl-main" / "root.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema_version": "1.0", "project_id": project_root.name, "timeline_id": "tl-main",
        "branch_id": "root", "canon_revision_id": canon_id, "vector_ready": True,
        "branch_lifecycle_status": "open", "collection_name": "fixture_rc2",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    alternate_manifest = manifest_path.with_name("alternate.json")
    alternate_manifest.write_text(json.dumps({
        "schema_version": "1.0", "project_id": project_root.name, "timeline_id": "tl-main",
        "branch_id": "alternate", "canon_revision_id": canon_id, "vector_ready": True,
        "branch_lifecycle_status": "open", "collection_name": "fixture_rc2_alternate",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # D-RC1: two production-schema, durable confirmed Turns.  These are
    # fixture-only records written through NarrativeTurnStore; the browser
    # still compiles them through the real compiler and state route.
    import hashlib
    from core.contracts.narrative_turn import (
        ActionType, NarrativeActionOption, NarrativeCustomActionPolicy,
        NarrativeScope, NarrativeTurnPlan, NarrativeTurnResult,
        NarrativeTurnTransition, ResultStatus, TurnState, new_id, now_utc,
    )
    from system.narrative_turn_store import NarrativeTurnStore
    turn_scope = NarrativeScope(project_root.name, "tl-main", "root")
    turn_store = NarrativeTurnStore(ctx)
    # Final RC starts from a clean Turn journal so Chromium itself proves the
    # two Confirm mutations and the distinct third deterministic context.
    seed_confirmed_turns = os.environ.get("STORYOS_FINAL_RC_EMPTY_TURNS") != "1"
    for number in ((1, 2) if seed_confirmed_turns else ()):
        turn_id = f"fixture-turn-{number}"
        actions = tuple(NarrativeActionOption(f"fixture-action-{number}-{choice}", ActionType.ADVANCE, f"Fixture action {number}-{choice}", f"fixture intent {choice}", (), (), (), (), "deterministic-planner", choice) for choice in (1, 2, 3))
        plan = NarrativeTurnPlan("1.0", turn_id, turn_scope, 1, "manual_v001", None, "a" * 64, "fixture-planner", canon_id, now_utc(), actions, NarrativeCustomActionPolicy(500, (), ("scope",)))
        result = NarrativeTurnResult("1.0", turn_id, turn_scope, 1, actions[0].action_id, None, ResultStatus.SUCCESS, f"Fixture confirmed Turn {number} advances the chapter.", (("fixture", str(number)),), (), "b" * 64, "fixture-revision", "c" * 64, now_utc(), f"fixture-confirm-{number}")
        turn_store.append_plan(plan); turn_store.append_result(result)
        previous_id = previous_fp = None; state = TurnState.PLANNED
        for next_state, reason in ((TurnState.AWAITING_ACTION, "plan"), (TurnState.VALIDATING, "validate"), (TurnState.VALIDATED, "validated"), (TurnState.PREVIEWED, "preview"), (TurnState.CONFIRMED, "confirm"), (TurnState.APPLIED_TO_BRANCH, "apply")):
            sequence = len(turn_store.get_transitions(turn_scope, turn_id)); fingerprint = hashlib.sha256(f"{turn_id}:{state.value}:{next_state.value}:{sequence}".encode()).hexdigest()
            transition = NarrativeTurnTransition("1.0", new_id("trn"), turn_id, turn_scope, state, next_state, reason, result.operation_id, now_utc(), fingerprint, sequence, previous_id, previous_fp)
            turn_store.append_transition(transition); previous_id, previous_fp, state = transition.transition_id, transition.record_fingerprint, next_state


def setup_workspace(workspace_root: Path) -> dict:
    """Create workspace with .story_os config and a project.
    Returns key identifiers.
    """
    projects_dir = workspace_root / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    project_id = "rc2-test-project"
    project_root = projects_dir / project_id
    seed_isolated_project(project_root)

    # Workspace config
    config_dir = workspace_root / ".story_os"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({
            "active_project": f"projects/{project_id}",
            "web": {"host": "127.0.0.1", "port": 7862, "open_browser": False},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Projects registry
    (config_dir / "projects.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "projects": [
                {
                    "project_id": project_id,
                    "project_root": f"projects/{project_id}",
                    "title": "RC2 测试项目",
                }
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "project_id": project_id,
        "timeline_id": "tl-main",
        "active_branch": "root",
        "inactive_branch": "alternate",
        "archived_branch": "old-route",
        "state_missing_branch": "state-missing",
        "chapter_id": 1,
    }


def main():
    import uvicorn

    tmp_dir = Path(tempfile.mkdtemp(prefix="rc2_browser_ws_"))
    info = setup_workspace(tmp_dir)
    os.chdir(tmp_dir)

    print("=" * 70)
    print("Phase 0D4-C-RC2 — Isolated Fixture Browser Server")
    print("=" * 70)
    print(f"Temp workspace: {tmp_dir}")
    print(f"Project ID:     {info['project_id']}")
    print(f"Timeline:       {info['timeline_id']}")
    print(f"Branches:       active={info['active_branch']}, "
          f"inactive={info['inactive_branch']}, "
          f"archived={info['archived_branch']}, "
          f"state-missing={info['state_missing_branch']}")
    print(f"Chapter:        {info['chapter_id']}")
    print()
    print("Quick URLs:")
    nturn_url = (
        f"http://127.0.0.1:7862/?mode=simulator&view=narrative-turn"
        f"&project_id={info['project_id']}&timeline_id={info['timeline_id']}"
        f"&branch_id={info['active_branch']}&chapter_id={info['chapter_id']}"
    )
    print(f"  Narrative Turn: {nturn_url}")
    print(f"  Reader Panel:   http://127.0.0.1:7862/?mode=simulator")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 70)

    # Import after chdir
    from web.app import app

    # Test-only transport faults. They wrap already-authoritative mutation
    # routes and drop exactly one successful response after the downstream app
    # has returned. Production code and production routes remain unchanged.
    # The audit file is intentionally inside the temporary project so browser
    # acceptance can prove request counts without exposing a production DTO.
    audit_path = tmp_dir / "projects" / info["project_id"] / ".drc1_network_audit.json"

    class MutationAuditAndResponseDrop:
        ROUTES = {
            "/api/narrative-chapter/compile": ("compile", "STORYOS_DRC_DROP_COMPILE_RESPONSE"),
            "/api/narrative-chapter/candidates/": ("review", "STORYOS_DRC_DROP_REVIEW_RESPONSE"),
            "/api/narrative-chapter/commit": ("commit", "STORYOS_DRC_DROP_COMMIT_RESPONSE"),
        }

        def __init__(self, downstream):
            self.downstream = downstream
            self.dropped = set()
            self.counts = {
                "confirm": 0, "compile": 0, "review": 0, "commit": 0,
                "branch_create": 0, "branch_select": 0,
                "branch_archive": 0, "branch_restore": 0,
            }
            self._write_audit()

        def _write_audit(self):
            audit_path.write_text(
                json.dumps({"requests": self.counts, "dropped": sorted(self.dropped)}, indent=2),
                encoding="utf-8",
            )

        def _kind(self, path):
            if path == "/api/narrative-turn/confirm":
                return ("confirm", "")
            if path == "/api/narrative-chapter/compile":
                return self.ROUTES[path]
            if path == "/api/narrative-chapter/commit":
                return self.ROUTES[path]
            if path.startswith("/api/narrative-chapter/candidates/") and path.endswith("/review"):
                return self.ROUTES["/api/narrative-chapter/candidates/"]
            for action in ("create", "select", "archive", "restore"):
                if path == f"/api/narrative-branches/{action}":
                    return (f"branch_{action}", "")
            return None

        async def __call__(self, scope, receive, send):
            route = self._kind(scope.get("path", "")) if scope.get("type") == "http" else None
            if route is None:
                await self.downstream(scope, receive, send)
                return
            kind, env_name = route
            self.counts[kind] += 1
            self._write_audit()
            messages = []

            async def capture(message):
                messages.append(message)

            await self.downstream(scope, receive, capture)
            successful = any(
                message.get("type") == "http.response.start"
                and int(message.get("status", 500)) < 400
                for message in messages
            )
            if env_name and os.environ.get(env_name) == "1" and kind not in self.dropped and successful:
                self.dropped.add(kind)
                self._write_audit()
                # Send only an incomplete response body, then close the
                # exchange. The route/service has already completed durably.
                start = next((message for message in messages if message.get("type") == "http.response.start"), None)
                if start:
                    await send(start)
                body = next((message for message in messages if message.get("type") == "http.response.body"), None)
                if body and body.get("body"):
                    await send({"type": "http.response.body", "body": body["body"][:1], "more_body": True})
                return
            for message in messages:
                await send(message)

    server_app = MutationAuditAndResponseDrop(app)

    # RC3-only transport fault. Keep this separate from D-RC1 so the existing
    # Confirm acceptance remains unchanged.
    if os.environ.get("STORYOS_RC3_DROP_CONFIRM_RESPONSE") == "1":
        class DropConfirmResponseAfterCompletion:
            def __init__(self, downstream):
                self.downstream = downstream
                self.dropped = False

            async def __call__(self, scope, receive, send):
                if scope.get("type") != "http" or scope.get("path") != "/api/narrative-turn/confirm" or self.dropped:
                    await self.downstream(scope, receive, send)
                    return
                messages = []
                async def capture(message):
                    messages.append(message)
                await self.downstream(scope, receive, capture)
                if any(message.get("type") == "http.response.start" and int(message.get("status", 500)) < 400 for message in messages):
                    self.dropped = True
                    (tmp_dir / "projects" / info["project_id"] / ".rc3_response_dropped.json").write_text(
                        json.dumps({"fault": "drop_next_confirm_response_after_durable_completion", "confirmed": True}),
                        encoding="utf-8",
                    )
                    raise ConnectionResetError("RC3 expected Confirm response interruption after durable completion")
                for message in messages:
                    await send(message)

        server_app = DropConfirmResponseAfterCompletion(server_app)

    uvicorn.run(server_app, host="127.0.0.1", port=7862, reload=False, log_level="info")


if __name__ == "__main__":
    main()
