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

    uvicorn.run(app, host="127.0.0.1", port=7862, reload=False, log_level="info")


if __name__ == "__main__":
    main()
