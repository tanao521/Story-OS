from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TODO_VERSION = "1.8"
VALID_TODO_TYPES = {
    "revision",
    "foreshadow",
    "worldbuilding",
    "character",
    "style",
    "continuity",
    "quality",
    "idea",
    "research",
    "other",
}
VALID_TODO_STATUSES = {"open", "in_progress", "done", "cancelled"}
VALID_TODO_PRIORITIES = {"low", "medium", "high", "urgent"}


def load_todos(data_dir: str | Path = "data") -> dict[str, Any]:
    path = _todos_json_path(data_dir)
    if not path.exists():
        return _empty_todos()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        todos = _empty_todos()
        todos["warnings"] = [f"todos.json 损坏，已返回空任务列表：{path.as_posix()}"]
        return todos
    if not isinstance(raw, dict):
        todos = _empty_todos()
        todos["warnings"] = [f"todos.json 结构无效，已返回空任务列表：{path.as_posix()}"]
        return todos
    return _normalize_todos(raw)


def save_todos(todos: dict[str, Any], data_dir: str | Path = "data") -> tuple[str, str]:
    normalized = _normalize_todos(todos)
    directory = Path(data_dir) / "todos"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "todos.json"
    markdown_path = directory / "todos.md"
    json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_todos_markdown(normalized), encoding="utf-8")
    return json_path.as_posix(), markdown_path.as_posix()


def create_todo(
    title: str,
    description: str = "",
    todo_type: str = "other",
    priority: str = "medium",
    chapter_id: int | None = None,
    related: dict[str, Any] | None = None,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    _validate_type(todo_type)
    _validate_priority(priority)
    if not title.strip():
        raise ValueError("任务标题不能为空")
    todos = load_todos(data_dir)
    now = _now()
    item = {
        "id": int(todos.get("next_id", 1) or 1),
        "title": title.strip(),
        "description": description,
        "status": "open",
        "priority": priority,
        "type": todo_type,
        "chapter_id": chapter_id,
        "related": _normalize_related(related),
        "created_at": now,
        "updated_at": now,
        "done_at": "",
    }
    todos.setdefault("items", []).append(item)
    todos["next_id"] = int(item["id"]) + 1
    save_todos(todos, data_dir)
    return item


def list_todos(
    status: str | None = None,
    todo_type: str | None = None,
    chapter_id: int | None = None,
    data_dir: str | Path = "data",
) -> list[dict[str, Any]]:
    if status is not None:
        _validate_status(status)
    if todo_type is not None:
        _validate_type(todo_type)
    items = list(load_todos(data_dir).get("items", []))
    if status is not None:
        items = [item for item in items if item.get("status") == status]
    if todo_type is not None:
        items = [item for item in items if item.get("type") == todo_type]
    if chapter_id is not None:
        items = [item for item in items if item.get("chapter_id") == chapter_id]
    return items


def update_todo_status(
    todo_id: int,
    status: str,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    _validate_status(status)
    todos = load_todos(data_dir)
    item = _find_todo(todos, todo_id)
    now = _now()
    item["status"] = status
    item["updated_at"] = now
    item["done_at"] = now if status == "done" else ""
    save_todos(todos, data_dir)
    return item


def edit_todo(
    todo_id: int,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    todo_type: str | None = None,
    chapter_id: int | None = None,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    if priority is not None:
        _validate_priority(priority)
    if todo_type is not None:
        _validate_type(todo_type)
    todos = load_todos(data_dir)
    item = _find_todo(todos, todo_id)
    if title is not None:
        if not title.strip():
            raise ValueError("任务标题不能为空")
        item["title"] = title.strip()
    if description is not None:
        item["description"] = description
    if priority is not None:
        item["priority"] = priority
    if todo_type is not None:
        item["type"] = todo_type
    if chapter_id is not None:
        item["chapter_id"] = chapter_id
    item["updated_at"] = _now()
    save_todos(todos, data_dir)
    return item


def delete_todo(
    todo_id: int,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    return update_todo_status(todo_id, "cancelled", data_dir)


def render_todos_markdown(todos: dict[str, Any]) -> str:
    normalized = _normalize_todos(todos)
    groups = [
        ("open", "Open", "[ ]"),
        ("in_progress", "In Progress", "[ ]"),
        ("done", "Done", "[x]"),
        ("cancelled", "Cancelled", "[ ]"),
    ]
    lines = ["# Story OS 待办事项", ""]
    for status, title, marker in groups:
        lines.extend([f"## {title}", ""])
        items = [item for item in normalized.get("items", []) if item.get("status") == status]
        if not items:
            lines.extend(["暂无", ""])
            continue
        for item in sorted(items, key=_sort_key):
            lines.append(f"- {marker} {_format_todo_brief(item)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def create_todos_from_quality_report(
    quality_report_path: str | Path,
    data_dir: str | Path = "data",
) -> list[dict[str, Any]]:
    path = Path(quality_report_path)
    if not path.exists():
        raise FileNotFoundError(path.as_posix())
    report = json.loads(path.read_text(encoding="utf-8"))
    chapter_id = int(report.get("chapter_id", 0) or 0) or None
    candidates = _quality_candidates(report, path)
    created: list[dict[str, Any]] = []
    for candidate in candidates:
        if _has_active_duplicate(candidate["title"], chapter_id, data_dir):
            continue
        created.append(
            create_todo(
                candidate["title"],
                description=candidate.get("description", ""),
                todo_type=candidate["type"],
                priority=candidate["priority"],
                chapter_id=chapter_id,
                related={
                    "quality_report_path": path.as_posix(),
                    "source": "quality_report",
                },
                data_dir=data_dir,
            )
        )
    return created


def summarize_todos(data_dir: str | Path = "data", current_chapter: int | None = None) -> dict[str, Any]:
    items = load_todos(data_dir).get("items", [])
    active = [item for item in items if item.get("status") in {"open", "in_progress"}]
    chapter_related = [
        item
        for item in active
        if current_chapter is not None
        and item.get("chapter_id") == current_chapter
        and item.get("type") in {"revision", "continuity"}
    ]
    top_items = sorted(active, key=_sort_key)[:5]
    return {
        "open_count": sum(1 for item in items if item.get("status") == "open"),
        "in_progress_count": sum(1 for item in items if item.get("status") == "in_progress"),
        "high_priority_count": sum(
            1 for item in active if item.get("priority") in {"high", "urgent"}
        ),
        "urgent_count": sum(1 for item in active if item.get("priority") == "urgent"),
        "chapter_related_open": chapter_related[:10],
        "top_items": top_items,
    }


def format_todo_for_cli(item: dict[str, Any]) -> str:
    return _format_todo_brief(item)


def _empty_todos() -> dict[str, Any]:
    return {"todo_version": TODO_VERSION, "next_id": 1, "items": []}


def _normalize_todos(raw: dict[str, Any]) -> dict[str, Any]:
    items = raw.get("items", [])
    if not isinstance(items, list):
        items = []
    normalized_items = [_normalize_item(item) for item in items if isinstance(item, dict)]
    next_id = int(raw.get("next_id", 1) or 1)
    if normalized_items:
        next_id = max(next_id, max(int(item.get("id", 0) or 0) for item in normalized_items) + 1)
    result = {
        "todo_version": str(raw.get("todo_version") or TODO_VERSION),
        "next_id": next_id,
        "items": normalized_items,
    }
    if raw.get("warnings"):
        result["warnings"] = raw["warnings"]
    return result


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    todo_type = str(item.get("type") or "other")
    priority = str(item.get("priority") or "medium")
    status = str(item.get("status") or "open")
    return {
        "id": int(item.get("id", 0) or 0),
        "title": str(item.get("title", "")),
        "description": str(item.get("description", "")),
        "status": status if status in VALID_TODO_STATUSES else "open",
        "priority": priority if priority in VALID_TODO_PRIORITIES else "medium",
        "type": todo_type if todo_type in VALID_TODO_TYPES else "other",
        "chapter_id": item.get("chapter_id") if item.get("chapter_id") is not None else None,
        "related": _normalize_related(item.get("related") if isinstance(item.get("related"), dict) else None),
        "created_at": str(item.get("created_at", "")),
        "updated_at": str(item.get("updated_at", "")),
        "done_at": str(item.get("done_at", "")),
    }


def _normalize_related(related: dict[str, Any] | None) -> dict[str, Any]:
    source = related or {}
    return {
        "character_ids": list(source.get("character_ids", [])) if isinstance(source.get("character_ids", []), list) else [],
        "foreshadow_ids": list(source.get("foreshadow_ids", [])) if isinstance(source.get("foreshadow_ids", []), list) else [],
        "quality_report_path": str(source.get("quality_report_path", "")),
        "version_path": str(source.get("version_path", "")),
        "source": str(source.get("source", "manual")),
    }


def _find_todo(todos: dict[str, Any], todo_id: int) -> dict[str, Any]:
    for item in todos.get("items", []):
        if int(item.get("id", 0) or 0) == todo_id:
            return item
    raise ValueError(f"未找到任务 #{todo_id}")


def _quality_candidates(report: dict[str, Any], path: Path) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for flag in report.get("flags", []):
        if not isinstance(flag, dict):
            continue
        flag_type = str(flag.get("type") or "quality")
        message = str(flag.get("message") or flag_type).strip()
        if not message:
            continue
        candidates.append(
            {
                "title": message,
                "description": f"来源质量报告：{path.as_posix()}",
                "type": _map_quality_type(flag_type),
                "priority": _map_severity(str(flag.get("severity") or "medium")),
            }
        )
    for suggestion in report.get("suggestions", []):
        if isinstance(suggestion, dict):
            title = str(suggestion.get("message") or suggestion.get("title") or "").strip()
            suggestion_type = str(suggestion.get("type") or "quality")
            severity = str(suggestion.get("severity") or "medium")
        else:
            title = str(suggestion).strip()
            suggestion_type = "quality"
            severity = "medium"
        if not title:
            continue
        candidates.append(
            {
                "title": title,
                "description": f"来源质量报告：{path.as_posix()}",
                "type": _map_quality_type(suggestion_type),
                "priority": _map_severity(severity),
            }
        )
    return candidates


def _has_active_duplicate(title: str, chapter_id: int | None, data_dir: str | Path) -> bool:
    for item in load_todos(data_dir).get("items", []):
        if item.get("title") == title and item.get("chapter_id") == chapter_id and item.get("status") not in {"done", "cancelled"}:
            return True
    return False


def _map_quality_type(flag_type: str) -> str:
    mapping = {
        "anti_ai_style": "style",
        "continuity": "continuity",
        "character_voice": "character",
        "hook_strength": "revision",
        "worldbuilding": "worldbuilding",
    }
    return mapping.get(flag_type, "quality")


def _map_severity(severity: str) -> str:
    mapping = {"high": "high", "medium": "medium", "low": "low"}
    return mapping.get(severity, "medium")


def _format_todo_brief(item: dict[str, Any]) -> str:
    chapter = item.get("chapter_id")
    chapter_part = f"[第{chapter}章]" if chapter is not None else ""
    return f"#{item.get('id')} [{item.get('priority')}][{item.get('type')}]{chapter_part} {item.get('title', '')}".strip()


def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
    priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return priority_rank.get(str(item.get("priority")), 4), int(item.get("id", 0) or 0)


def _validate_type(todo_type: str) -> None:
    if todo_type not in VALID_TODO_TYPES:
        raise ValueError(f"非法任务类型：{todo_type}")


def _validate_status(status: str) -> None:
    if status not in VALID_TODO_STATUSES:
        raise ValueError(f"非法任务状态：{status}")


def _validate_priority(priority: str) -> None:
    if priority not in VALID_TODO_PRIORITIES:
        raise ValueError(f"非法优先级：{priority}")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _todos_json_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "todos" / "todos.json"
