from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters
from core.draft_writer import write_chapter_draft
from core.next_chapter_planner import plan_next_chapter
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible
from system.context_builder import (
    build_state_snapshot,
    build_working_context,
    get_recent_chapters,
    render_context_markdown,
    retrieve_old_summaries,
    save_current_context,
)


def make_state() -> dict[str, Any]:
    state = build_initial_state({"world_style": "近未来末世"})
    state["current_chapter"] = 6
    state["foreshadows"] = [
        {"id": "fs_001", "content": "开放伏笔", "status": "open"},
        {"id": "fs_002", "content": "计划伏笔", "status": "planned"},
        {"id": "fs_003", "content": "关闭伏笔", "status": "closed"},
    ]
    state["timeline"] = [{"chapter_id": index, "event": f"事件{index}"} for index in range(1, 8)]
    return state


def make_memory_index(tmp_path: Path, count: int = 6) -> dict[str, Any]:
    chapters = []
    for chapter_id in range(1, count + 1):
        chapter_path = tmp_path / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"
        summary_path = tmp_path / "data" / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(f"# 第{chapter_id}章\n\n原文{chapter_id}", encoding="utf-8")
        summary = {
            "chapter_id": chapter_id,
            "chapter_title": f"章节{chapter_id}",
            "short_summary": f"摘要{chapter_id} 秘密 资源",
            "memory_tags": ["秘密", f"tag{chapter_id}"],
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": f"章节{chapter_id}",
                "chapter_path": chapter_path.as_posix(),
                "summary_path": summary_path.as_posix(),
                "memory_tags": summary["memory_tags"],
                "short_summary": summary["short_summary"],
            }
        )
    return {"memory_version": "0.6", "working_context_chapters": 3, "chapters": chapters}


def test_build_state_snapshot_returns_dict() -> None:
    snapshot = build_state_snapshot(make_state())

    assert isinstance(snapshot, dict)


def test_open_foreshadows_only_contains_open_or_planned() -> None:
    snapshot = build_state_snapshot(make_state())

    assert {item["status"] for item in snapshot["open_foreshadows"]} == {"open", "planned"}


def test_timeline_tail_keeps_at_most_five_items() -> None:
    snapshot = build_state_snapshot(make_state())

    assert len(snapshot["timeline_tail"]) <= 5


def test_get_recent_chapters_returns_at_most_three(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)

    recent = get_recent_chapters(memory_index, current_chapter=6)

    assert len(recent) <= 3


def test_get_recent_chapters_does_not_read_older_raw_text(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)

    recent = get_recent_chapters(memory_index, current_chapter=6)

    assert {item["chapter_id"] for item in recent} == {4, 5, 6}


def test_retrieve_old_summaries_excludes_recent_three(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)

    retrieved = retrieve_old_summaries(memory_index, 6, "秘密", [4, 5, 6])

    assert all(item["chapter_id"] not in {4, 5, 6} for item in retrieved)


def test_retrieve_old_summaries_returns_at_most_five(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=10)

    retrieved = retrieve_old_summaries(memory_index, 10, "", [8, 9, 10])

    assert len(retrieved) <= 5


def test_build_working_context_returns_sliding_window_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)

    context = build_working_context(make_state(), memory_index, "秘密")

    assert context["mode"] == "sliding_window_plus_summary_retrieval"


def test_memory_budget_recent_chapters_count_is_at_most_three(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)

    context = build_working_context(make_state(), memory_index, "秘密")

    assert context["memory_budget"]["recent_chapters_count"] <= 3


def test_render_context_markdown_contains_title(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)
    context = build_working_context(make_state(), memory_index, "秘密")

    markdown = render_context_markdown(context)

    assert "# 当前写作上下文包" in markdown


def test_save_current_context_writes_json_and_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_index = make_memory_index(tmp_path, count=6)
    context = build_working_context(make_state(), memory_index, "秘密")

    json_path, markdown_path = save_current_context(context)

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()


def test_write_draft_without_context_still_runs_with_warning() -> None:
    story_spec = {
        "title": "未命名小说",
        "genre": "末世",
        "length_type": "长篇",
        "target_word_count": 300000,
        "world_style": "近未来末世",
        "tone": "灰暗但不绝望",
        "writing_style": "电影感",
        "narration": "第三人称有限视角",
        "character_structure": "群像文",
        "romance_level": "轻微",
        "focus": ["生存"],
        "avoid": [],
        "anti_ai_style_rules": [],
        "need_outline": True,
    }
    blueprint = generate_blueprint(story_spec)
    state = build_initial_state(story_spec)
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, plan)

    assert any("current_context.json" in warning for warning in draft["self_check"]["warnings"])
