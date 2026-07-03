from __future__ import annotations

from pathlib import Path

import pytest

from system.todo_manager import (
    create_todo,
    delete_todo,
    list_todos,
    load_todos,
    render_todos_markdown,
    update_todo_status,
)


def test_load_todos_returns_empty_when_missing(tmp_path: Path) -> None:
    todos = load_todos(tmp_path / "data")

    assert todos["todo_version"] == "1.8"
    assert todos["next_id"] == 1
    assert todos["items"] == []


def test_create_todo_adds_item(tmp_path: Path) -> None:
    item = create_todo("补全避难所规则", data_dir=tmp_path / "data")

    assert item["title"] == "补全避难所规则"
    assert load_todos(tmp_path / "data")["items"][0]["id"] == item["id"]


def test_id_auto_increments(tmp_path: Path) -> None:
    first = create_todo("任务一", data_dir=tmp_path / "data")
    second = create_todo("任务二", data_dir=tmp_path / "data")

    assert second["id"] == first["id"] + 1


def test_default_status_is_open(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")

    assert item["status"] == "open"


def test_default_priority_is_medium(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")

    assert item["priority"] == "medium"


def test_invalid_type_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_todo("任务", todo_type="bad", data_dir=tmp_path / "data")


def test_invalid_priority_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_todo("任务", priority="bad", data_dir=tmp_path / "data")


def test_list_todos_filters_by_status(tmp_path: Path) -> None:
    first = create_todo("任务一", data_dir=tmp_path / "data")
    create_todo("任务二", data_dir=tmp_path / "data")
    update_todo_status(first["id"], "done", tmp_path / "data")

    open_items = list_todos(status="open", data_dir=tmp_path / "data")

    assert len(open_items) == 1
    assert open_items[0]["title"] == "任务二"


def test_list_todos_filters_by_type(tmp_path: Path) -> None:
    create_todo("伏笔提醒", todo_type="foreshadow", data_dir=tmp_path / "data")
    create_todo("文风问题", todo_type="style", data_dir=tmp_path / "data")

    items = list_todos(todo_type="style", data_dir=tmp_path / "data")

    assert len(items) == 1
    assert items[0]["title"] == "文风问题"


def test_update_todo_status_sets_done(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")

    updated = update_todo_status(item["id"], "done", tmp_path / "data")

    assert updated["status"] == "done"


def test_done_writes_done_at(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")

    updated = update_todo_status(item["id"], "done", tmp_path / "data")

    assert updated["done_at"]


def test_reopen_clears_done_at(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")
    update_todo_status(item["id"], "done", tmp_path / "data")

    reopened = update_todo_status(item["id"], "open", tmp_path / "data")

    assert reopened["done_at"] == ""


def test_delete_todo_sets_cancelled(tmp_path: Path) -> None:
    item = create_todo("任务", data_dir=tmp_path / "data")

    deleted = delete_todo(item["id"], tmp_path / "data")

    assert deleted["status"] == "cancelled"


def test_render_todos_markdown_contains_title(tmp_path: Path) -> None:
    create_todo("任务", data_dir=tmp_path / "data")

    markdown = render_todos_markdown(load_todos(tmp_path / "data"))

    assert "# Story OS 待办事项" in markdown
