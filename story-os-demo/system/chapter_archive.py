from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ChapterArchiveError(Exception):
    pass


def archive_chapter(chapter_number: int, data_dir: str | Path = "data", reason: str = "user_archived") -> dict[str, Any]:
    if chapter_number < 1:
        raise ChapterArchiveError("chapter_number must be >= 1")
    root = Path(data_dir)
    chapter_code = f"{chapter_number:03d}"
    archive_root = root / "archive" / "chapters" / f"chapter_{chapter_code}"
    sources = _related_files(root, chapter_code)
    if not sources:
        if (archive_root / "archive_meta.json").exists():
            raise ChapterArchiveError(f"chapter_{chapter_code} is already archived.")
        raise ChapterArchiveError(f"chapter_{chapter_code} has no local files to archive.")

    planned = [(source, archive_root / source.relative_to(root)) for source in sources]
    moved: list[tuple[Path, Path]] = []
    state_path = root / "state.json"
    original_state = _load_json(state_path, {})
    memory_path = root / "memory" / "memory_index.json"
    original_memory = _load_json(memory_path, {})

    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        for source, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            moved.append((source, target))

        meta = _build_archive_meta(chapter_number, reason, root, archive_root, moved, original_state)
        _write_json_atomic(archive_root / "archive_meta.json", meta)
        updated_memory = _mark_memory_archived(original_memory, chapter_number, archive_root / "archive_meta.json")
        if updated_memory is not None:
            _write_json_atomic(memory_path, updated_memory)
        updated_state = _updated_state(original_state, chapter_number, root, archive_root / "archive_meta.json")
        _write_json_atomic(state_path, updated_state)
    except Exception:
        _rollback_moves(moved)
        raise

    result = {
        "chapter": chapter_number,
        "archive_dir": archive_root.as_posix(),
        "archive_meta_path": (archive_root / "archive_meta.json").as_posix(),
        "files": meta["files"],
        "state": {
            "current_chapter_before": int(original_state.get("current_chapter", 0) or 0) if isinstance(original_state, dict) else 0,
            "current_chapter_after": int(updated_state.get("current_chapter", 0) or 0),
        },
        "external_cleanup": meta["external_cleanup"],
    }
    # Advisory only: archive completion must never be blocked by planning control.
    try:
        from core.project_context import get_project_context
        from planning_engine.rolling_integration import mark_rolling_window_dirty
        result["rolling_window_notice"] = mark_rolling_window_dirty(get_project_context(root.parent), "chapter_archived")
    except Exception as exc:
        result["rolling_window_notice"] = {"changed": False, "warning": f"Rolling window status check failed: {str(exc)[:160]}"}
    return result


def is_chapter_archived(chapter_number: int, data_dir: str | Path = "data") -> bool:
    root = Path(data_dir)
    chapter_code = f"{chapter_number:03d}"
    if (root / "archive" / "chapters" / f"chapter_{chapter_code}" / "archive_meta.json").exists():
        return True
    state = _load_json(root / "state.json", {})
    archived = state.get("archived_chapters", []) if isinstance(state, dict) else []
    return any(_archived_chapter_id(item) == chapter_number for item in archived)


def is_memory_chapter_active(chapter: dict[str, Any]) -> bool:
    return not bool(chapter.get("archived") or chapter.get("excluded_from_context"))


def active_chapter_ids(data_dir: str | Path = "data") -> list[int]:
    root = Path(data_dir)
    ids = []
    for path in sorted((root / "chapters").glob("chapter_*.md")):
        parsed = _chapter_id_from_name(path.name)
        if parsed and not is_chapter_archived(parsed, root):
            ids.append(parsed)
    return ids


def active_chapter_entries(data_dir: str | Path = "data") -> list[dict[str, Any]]:
    root = Path(data_dir)
    memory = _load_json(root / "memory" / "memory_index.json", {})
    entries = memory.get("chapters", []) if isinstance(memory, dict) else []
    result: list[dict[str, Any]] = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict) or not is_memory_chapter_active(item):
                continue
            chapter_id = int(item.get("chapter_id", 0) or 0)
            if chapter_id and not is_chapter_archived(chapter_id, root):
                result.append({
                    "chapter_id": chapter_id,
                    "title": str(item.get("title", "")),
                    "chapter_path": str(item.get("chapter_path", "")),
                })
    if result:
        for entry in result:
            chapter_id = int(entry.get("chapter_id", 0) or 0)
            chapter_path = root / "chapters" / f"chapter_{chapter_id:03d}.md"
            file_title = _chapter_file_title(chapter_path)
            if file_title:
                entry["title"] = file_title
        return sorted(result, key=lambda item: int(item.get("chapter_id", 0) or 0))
    return [
        {"chapter_id": chapter_id, "title": "", "chapter_path": (root / "chapters" / f"chapter_{chapter_id:03d}.md").as_posix()}
        for chapter_id in active_chapter_ids(root)
    ]


def _chapter_file_title(path: Path) -> str:
    import re
    if not path.exists():
        return ""
    try:
        first = path.read_text(encoding="utf-8").lstrip().splitlines()[0].strip()
    except (OSError, UnicodeError, IndexError):
        return ""
    match = re.match(r"^#\s*第[一二三四五六七八九十百千\d]+章\s+(.+?)\s*$", first)
    return match.group(1).strip() if match else ""

def _related_files(root: Path, chapter_code: str) -> list[Path]:
    candidates: list[Path] = []
    fixed = [
        root / "chapters" / f"chapter_{chapter_code}.md",
        root / "summaries" / f"chapter_{chapter_code}_summary.json",
        root / "summaries" / f"chapter_{chapter_code}_summary.md",
        root / "versions" / f"chapter_{chapter_code}_versions.json",
    ]
    candidates.extend(path for path in fixed if path.exists() and path.is_file())
    for directory in ["drafts", "edited", "manual", "pipeline_runs", "quality_reports", "continuity_reports"]:
        folder = root / directory
        if not folder.exists():
            continue
        candidates.extend(path for path in folder.glob(f"*chapter_{chapter_code}*") if path.is_file())
    return sorted(set(candidates), key=lambda path: path.as_posix())


def _build_archive_meta(
    chapter_number: int,
    reason: str,
    root: Path,
    archive_root: Path,
    moved: list[tuple[Path, Path]],
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chapter": chapter_number,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "files": [
            {"source": source.relative_to(root).as_posix(), "archived_path": target.relative_to(archive_root).as_posix()}
            for source, target in moved
        ],
        "external_cleanup": {
            "obsidian": "not_performed",
            "vector_memory": "not_performed",
            "note": "External Obsidian and vector memory are not deleted by safe archive.",
        },
        "previous_state": {
            "current_chapter": state.get("current_chapter", 0) if isinstance(state, dict) else 0,
            "current_stage": state.get("current_stage", "") if isinstance(state, dict) else "",
        },
    }


def _updated_state(state: dict[str, Any], chapter_number: int, root: Path, meta_path: Path) -> dict[str, Any]:
    updated = dict(state) if isinstance(state, dict) else {}
    archived = [item for item in updated.get("archived_chapters", []) if _archived_chapter_id(item) != chapter_number]
    archived.append({
        "chapter": chapter_number,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "reason": "user_archived",
        "archive_meta_path": meta_path.as_posix(),
    })
    updated["archived_chapters"] = sorted(archived, key=_archived_chapter_id)
    active_ids = active_chapter_ids(root)
    current = int(updated.get("current_chapter", 0) or 0)
    if current == chapter_number or current > (max(active_ids) if active_ids else 0):
        updated["current_chapter"] = max(active_ids) if active_ids else 0
    if isinstance(updated.get("last_committed_chapter"), dict) and int(updated["last_committed_chapter"].get("chapter_id", 0) or 0) == chapter_number:
        updated["last_committed_chapter"] = _last_active_chapter(root)
    return updated


def _mark_memory_archived(memory: dict[str, Any], chapter_number: int, meta_path: Path) -> dict[str, Any] | None:
    if not isinstance(memory, dict) or not isinstance(memory.get("chapters"), list):
        return None
    updated = dict(memory)
    chapters = []
    for item in memory["chapters"]:
        if not isinstance(item, dict):
            chapters.append(item)
            continue
        if int(item.get("chapter_id", 0) or 0) == chapter_number:
            next_item = dict(item)
            next_item["archived"] = True
            next_item["excluded_from_context"] = True
            next_item["archive_meta_path"] = meta_path.as_posix()
            chapters.append(next_item)
        else:
            chapters.append(item)
    updated["chapters"] = chapters
    return updated


def _last_active_chapter(root: Path) -> dict[str, Any]:
    entries = active_chapter_entries(root)
    if not entries:
        return {}
    latest = entries[-1]
    return {
        "chapter_id": latest["chapter_id"],
        "title": latest.get("title", ""),
        "chapter_path": latest.get("chapter_path", ""),
        "summary_path": (root / "summaries" / f"chapter_{int(latest['chapter_id']):03d}_summary.json").as_posix(),
    }


def _rollback_moves(moved: list[tuple[Path, Path]]) -> None:
    for source, target in reversed(moved):
        if target.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            target.replace(source)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (PermissionError, FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _chapter_id_from_name(name: str) -> int:
    prefix = "chapter_"
    if not name.startswith(prefix):
        return 0
    digits = name[len(prefix):len(prefix) + 3]
    return int(digits) if digits.isdigit() else 0


def _archived_chapter_id(item: Any) -> int:
    if isinstance(item, dict):
        return int(item.get("chapter", item.get("chapter_id", 0)) or 0)
    try:
        return int(item)
    except (TypeError, ValueError):
        return 0
