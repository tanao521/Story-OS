from __future__ import annotations

from typing import Any

from core.chapter_committer import commit_chapter, render_committed_chapter_markdown


def make_plan() -> dict[str, Any]:
    return {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "chapter_goal": "完成当前章目标",
        "conflict_design": {"main_conflict": "当前章冲突"},
        "climax_design": {"climax_event": "当前章事件"},
        "required_context": {
            "characters_to_use": [{"id": "char_001", "name": "林声"}],
            "world_rules_to_use": [{"id": "rule_001", "rule": "规则"}],
        },
    }


def make_state() -> dict[str, Any]:
    return {
        "current_chapter": 0,
        "current_stage": "chapter_draft_edited",
        "foreshadows": [],
        "timeline": [],
        "plot": {"completed_events": []},
    }


def test_commit_uses_edited_text_when_edited_payload_exists(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    edited = {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "draft_text": "草稿正文",
        "edited_text": "编辑版正文",
    }

    result = commit_chapter(edited, make_plan(), make_state(), {}, {}, {})
    markdown = render_committed_chapter_markdown(edited)

    assert result["source_used"] == "edited"
    assert "编辑版正文" in markdown
    assert "草稿正文" not in markdown


def test_commit_uses_draft_text_when_edited_payload_missing(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    draft = {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "draft_text": "草稿正文",
    }

    result = commit_chapter(draft, make_plan(), make_state(), {}, {}, {})
    markdown = render_committed_chapter_markdown(draft)

    assert result["source_used"] == "draft"
    assert "草稿正文" in markdown


def test_commit_result_contains_source_used(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = commit_chapter(
        {"chapter_id": 1, "chapter_title": "测试章", "draft_text": "草稿正文"},
        make_plan(),
        make_state(),
        {},
        {},
        {},
    )

    assert "source_used" in result
    assert result["source_used"] in {"edited", "draft"}


def test_commit_still_commits_only_current_chapter_and_advances(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    state = make_state()

    result = commit_chapter(
        {"chapter_id": 1, "chapter_title": "测试章", "edited_text": "编辑版正文"},
        make_plan(),
        state,
        {},
        {},
        {},
    )

    assert result["chapter_id"] == 1
    assert state["current_chapter"] == 1
