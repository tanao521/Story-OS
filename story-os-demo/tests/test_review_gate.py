from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from system.review_gate import (
    create_review_record,
    find_current_review_target,
    load_review_record,
    render_review_markdown,
    save_review_record,
    update_review_status,
)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_target() -> dict[str, Any]:
    return {
        "chapter_id": 1,
        "chapter_title": "测试章",
        "source_type": "edited",
        "json_path": "data/edited/chapter_001_edited.json",
        "markdown_path": "data/edited/chapter_001_edited.md",
        "text": "正文",
    }


def test_create_review_record_returns_pending_status() -> None:
    record = create_review_record(make_target())

    assert record["status"] == "pending"


def test_save_and_load_review_record(tmp_path: Any) -> None:
    record = create_review_record(make_target())

    path = save_review_record(record, tmp_path)
    loaded = load_review_record(1, tmp_path)

    assert Path(path).exists()
    assert loaded["chapter_id"] == 1


def test_update_review_status_approved(tmp_path: Any) -> None:
    record = create_review_record(make_target())
    save_review_record(record, tmp_path)

    updated = update_review_status(1, "approved", decision="approve", data_dir=tmp_path)

    assert updated["status"] == "approved"
    assert updated["decision"] == "approve"


def test_update_review_status_rejects_invalid_status(tmp_path: Any) -> None:
    with pytest.raises(ValueError):
        update_review_status(1, "bad", data_dir=tmp_path)


def test_find_current_review_target_prefers_edited(tmp_path: Any) -> None:
    write_json(tmp_path / "next_chapter_plan.json", {"chapter_id": 1, "chapter_title": "测试章"})
    write_json(tmp_path / "drafts" / "chapter_001_draft.json", {"chapter_id": 1, "draft_text": "草稿"})
    write_json(tmp_path / "edited" / "chapter_001_edited.json", {"chapter_id": 1, "edited_text": "编辑版"})

    target = find_current_review_target(tmp_path)

    assert target["source_type"] == "edited"
    assert target["text"] == "编辑版"


def test_find_current_review_target_uses_draft_when_no_edited(tmp_path: Any) -> None:
    write_json(tmp_path / "next_chapter_plan.json", {"chapter_id": 1, "chapter_title": "测试章"})
    write_json(tmp_path / "drafts" / "chapter_001_draft.json", {"chapter_id": 1, "draft_text": "草稿"})

    target = find_current_review_target(tmp_path)

    assert target["source_type"] == "draft"
    assert target["text"] == "草稿"


def test_render_review_markdown_contains_title_prefix() -> None:
    record = create_review_record(make_target())

    markdown = render_review_markdown(record, make_target())

    assert "# 第" in markdown
