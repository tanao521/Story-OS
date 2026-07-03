from __future__ import annotations

from typing import Any

import config
from core.draft_editor import (
    build_state_snapshot_for_editing,
    edit_draft,
    is_valid_edited_text,
    local_rule_edit,
    render_edited_markdown,
)


def long_text() -> str:
    return "显然，他不是害怕，而是在等待。可以看出，走廊尽头的灯闪了一下。总之，他必须继续往前。" * 30


def make_draft() -> dict[str, Any]:
    return {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "draft_text": long_text(),
    }


def make_plan() -> dict[str, Any]:
    return {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "chapter_goal": "继续往前并确认走廊尽头的异常",
        "conflict_design": {"main_conflict": "未知声音逼近"},
        "pacing_design": {"ending_hook": "灯闪了一下"},
    }


def test_build_state_snapshot_for_editing_returns_dict() -> None:
    snapshot = build_state_snapshot_for_editing({"current_chapter": 0})

    assert isinstance(snapshot, dict)


def test_open_foreshadows_only_include_open_or_planned() -> None:
    snapshot = build_state_snapshot_for_editing(
        {
            "foreshadows": [
                {"id": "a", "status": "open"},
                {"id": "b", "status": "planned"},
                {"id": "c", "status": "closed"},
            ]
        }
    )

    assert [item["id"] for item in snapshot["open_foreshadows"]] == ["a", "b"]


def test_timeline_tail_keeps_at_most_five_items() -> None:
    snapshot = build_state_snapshot_for_editing({"timeline": [{"i": i} for i in range(8)]})

    assert len(snapshot["timeline_tail"]) == 5
    assert snapshot["timeline_tail"][0]["i"] == 3


def test_local_rule_edit_removes_summary_words() -> None:
    edited, warnings = local_rule_edit(long_text())

    assert "显然" not in edited
    assert "总之" not in edited
    assert "可以看出" not in edited
    assert warnings


def test_is_valid_edited_text_rejects_empty_text() -> None:
    assert is_valid_edited_text("", long_text()) is False


def test_is_valid_edited_text_rejects_json_text() -> None:
    assert is_valid_edited_text('{"edited_text": "x"}', long_text()) is False


def test_edit_draft_falls_back_to_local_rule_when_deepseek_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "USE_DEEPSEEK_FOR_EDITING", True)
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")

    edited = edit_draft(
        make_draft(),
        make_plan(),
        {},
        {},
        {},
        {},
        {"current_chapter": 0},
        None,
    )

    assert edited["status"] == "edited"
    assert edited["editing"]["mode"] == "local_rule"
    assert edited["editing"]["fallback_used"] is True
    assert "editing" in edited


def test_render_edited_markdown_contains_title_prefix() -> None:
    edited = edit_draft(make_draft(), make_plan(), {}, {}, {}, {}, {"current_chapter": 0})

    markdown = render_edited_markdown(edited)

    assert "# 第" in markdown
