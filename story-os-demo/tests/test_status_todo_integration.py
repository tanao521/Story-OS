from __future__ import annotations

import json
from pathlib import Path

from system.status_dashboard import build_status_dashboard
from system.todo_manager import create_todo


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path) -> None:
    write_json(root / "data" / "story_spec.json", {"title": "Todo Novel"})
    write_json(root / "data" / "story_blueprint.json", {"title": "Todo Novel"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"continuity_rules": []})
    write_json(root / "data" / "state.json", {"current_chapter": 2, "current_stage": "chapter_committed"})
    write_json(root / "data" / "next_chapter_plan.json", {"chapter_id": 3, "chapter_title": "下一章"})


def test_status_counts_open_todos(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    create_todo("处理伏笔", data_dir=tmp_path / "data")

    status = build_status_dashboard(tmp_path / "data")

    assert status["todos"]["open_count"] == 1


def test_status_counts_high_priority_todos(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    create_todo("重写结尾", priority="high", data_dir=tmp_path / "data")

    status = build_status_dashboard(tmp_path / "data")

    assert status["todos"]["high_priority_count"] == 1


def test_urgent_todo_becomes_first_next_action(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    create_todo("立刻处理连贯性", priority="urgent", data_dir=tmp_path / "data")

    status = build_status_dashboard(tmp_path / "data")

    assert status["next_actions"][0]["command"] == "python main.py todo list --status open"


def test_current_chapter_revision_todo_blocks_approval_recommendation(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    create_todo("先修第3章钩子", todo_type="revision", chapter_id=3, data_dir=tmp_path / "data")

    status = build_status_dashboard(tmp_path / "data")

    assert status["next_actions"][0]["command"] == "python main.py todo list --chapter 3"
