from __future__ import annotations

from typing import Any

from core.blueprint_generator import generate_blueprint
from core.chapter_committer import (
    apply_state_updates,
    commit_chapter,
    summarize_chapter,
    update_memory_index,
)
from core.character_builder import generate_characters
from core.draft_writer import write_chapter_draft
from core.next_chapter_planner import plan_next_chapter
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible


def make_story_spec() -> dict[str, Any]:
    return {
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
        "focus": ["生存", "人物成长"],
        "avoid": ["不要流水账"],
        "anti_ai_style_rules": ["减少破折号"],
        "need_outline": True,
    }


def make_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    story_spec = make_story_spec()
    blueprint = generate_blueprint(story_spec)
    state = build_initial_state(story_spec)
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    chapter_plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)
    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)
    return story_spec, blueprint, characters, world_bible, state, chapter_plan, draft


def test_summarize_chapter_returns_dict() -> None:
    *_, chapter_plan, draft = make_inputs()

    summary = summarize_chapter(draft, chapter_plan)

    assert isinstance(summary, dict)


def test_summary_contains_short_summary() -> None:
    *_, chapter_plan, draft = make_inputs()

    summary = summarize_chapter(draft, chapter_plan)

    assert summary["short_summary"]


def test_summary_contains_key_events() -> None:
    *_, chapter_plan, draft = make_inputs()

    summary = summarize_chapter(draft, chapter_plan)

    assert summary["key_events"]


def test_apply_state_updates_sets_current_chapter_to_chapter_id() -> None:
    *_, state, chapter_plan, draft = make_inputs()
    summary = summarize_chapter(draft, chapter_plan)

    apply_state_updates(state, chapter_plan, summary)

    assert state["current_chapter"] == chapter_plan["chapter_id"]


def test_apply_state_updates_appends_completed_events() -> None:
    *_, state, chapter_plan, draft = make_inputs()
    summary = summarize_chapter(draft, chapter_plan)

    apply_state_updates(state, chapter_plan, summary)

    assert state["plot"]["completed_events"]


def test_apply_state_updates_appends_timeline() -> None:
    *_, state, chapter_plan, draft = make_inputs()
    summary = summarize_chapter(draft, chapter_plan)

    apply_state_updates(state, chapter_plan, summary)

    assert state["timeline"]


def test_apply_state_updates_does_not_delete_existing_characters() -> None:
    *_, state, chapter_plan, draft = make_inputs()
    state["characters"]["旧角色"] = {"physical": "原状态"}
    summary = summarize_chapter(draft, chapter_plan)

    apply_state_updates(state, chapter_plan, summary)

    assert "旧角色" in state["characters"]


def test_update_memory_index_generates_memory_index_structure(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    *_, chapter_plan, draft = make_inputs()
    summary = summarize_chapter(draft, chapter_plan)

    memory_index = update_memory_index(
        summary,
        "data/chapters/chapter_001.md",
        "data/summaries/chapter_001_summary.json",
    )

    assert memory_index["memory_version"] == "0.6"
    assert memory_index["chapters"]


def test_commit_chapter_returns_committed_status(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    story_spec, _, characters, world_bible, state, chapter_plan, draft = make_inputs()

    result = commit_chapter(draft, chapter_plan, state, story_spec, characters, world_bible)

    assert result["status"] == "committed"


def test_commit_chapter_returns_summary_and_state_patch(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    story_spec, _, characters, world_bible, state, chapter_plan, draft = make_inputs()

    result = commit_chapter(draft, chapter_plan, state, story_spec, characters, world_bible)

    assert result["summary"]
    assert result["state_patch"]


def test_duplicate_foreshadows_are_not_added_twice() -> None:
    *_, state, chapter_plan, draft = make_inputs()
    summary = summarize_chapter(draft, chapter_plan)
    duplicate = summary["foreshadows_planted"][0]["content"]
    state["foreshadows"] = [{"id": "fs_001", "content": duplicate, "status": "open"}]

    apply_state_updates(state, chapter_plan, summary)

    contents = [item["content"] for item in state["foreshadows"]]
    assert contents.count(duplicate) == 1


def test_commit_chapter_only_commits_one_chapter(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    story_spec, _, characters, world_bible, state, chapter_plan, draft = make_inputs()

    result = commit_chapter(draft, chapter_plan, state, story_spec, characters, world_bible)

    assert result["chapter_id"] == chapter_plan["chapter_id"]
    assert state["current_chapter"] == chapter_plan["chapter_id"]
