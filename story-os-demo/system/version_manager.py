from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from system.chapter_archive import is_chapter_archived


VALID_SOURCE_TYPES = {"draft", "edited", "manual"}


class VersionArchiveError(Exception):
    pass


def format_chapter_id(chapter_id: int) -> str:
    return f"{chapter_id:03d}"


def get_next_version_number(chapter_id: int, kind: str, data_dir: str | Path = "data") -> int:
    _validate_source_type(kind)
    versions = list_versions(chapter_id, data_dir)
    key = _collection_key(kind)
    existing = [int(item.get("version", 0) or 0) for item in versions.get(key, [])]
    return (max(existing) if existing else 0) + 1


def build_versioned_paths(
    chapter_id: int,
    kind: str,
    version: int,
    data_dir: str | Path = "data",
) -> dict[str, str]:
    _validate_source_type(kind)
    chapter_code = format_chapter_id(chapter_id)
    version_code = f"v{version:03d}"
    directory = Path(data_dir) / _directory_name(kind)
    stem = f"chapter_{chapter_code}_{kind}_{version_code}"
    return {
        "json_path": (directory / f"{stem}.json").as_posix(),
        "markdown_path": (directory / f"{stem}.md").as_posix(),
    }


def list_versions(chapter_id: int, data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    existing = _read_index_if_exists(chapter_id, root)
    if is_chapter_archived(chapter_id, root):
        return {
            "version_index": "1.5",
            "chapter_id": chapter_id,
            "drafts": [],
            "edited": [],
            "manual": [],
            "selected": {},
        }
    drafts = _scan_kind(root, chapter_id, "draft")
    edited = _scan_kind(root, chapter_id, "edited")
    manual = _scan_kind(root, chapter_id, "manual")
    selected = existing.get("selected", {}) if isinstance(existing.get("selected"), dict) else {}
    if selected and not _find_version_in_lists(drafts, edited, manual, selected):
        selected = {}
    return {
        "version_index": "1.5",
        "chapter_id": chapter_id,
        "drafts": drafts,
        "edited": edited,
        "manual": manual,
        "selected": selected,
    }


def save_versions_index(
    chapter_id: int,
    versions: dict[str, Any],
    data_dir: str | Path = "data",
) -> str:
    path = _index_path(chapter_id, Path(data_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    versions["version_index"] = versions.get("version_index", "1.5")
    versions["chapter_id"] = chapter_id
    path.write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.as_posix()


def load_versions_index(chapter_id: int, data_dir: str | Path = "data") -> dict[str, Any]:
    versions = list_versions(chapter_id, data_dir)
    save_versions_index(chapter_id, versions, data_dir)
    return versions


def select_version(
    chapter_id: int,
    source_type: str,
    version: int,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    _validate_source_type(source_type)
    versions = list_versions(chapter_id, data_dir)
    match = _find_version(versions, source_type, version)
    if not match:
        raise FileNotFoundError(f"chapter_{format_chapter_id(chapter_id)} {source_type}:{version} 不存在")
    selected = {
        "source_type": source_type,
        "version": version,
        "version_label": match.get("version_label", f"{source_type}_v{version:03d}"),
        "json_path": match.get("json_path", ""),
        "markdown_path": match.get("markdown_path", ""),
        "selected_at": _path_mtime(match.get("json_path", "")),
    }
    versions["selected"] = selected
    save_versions_index(chapter_id, versions, data_dir)
    return selected


def archive_version(
    chapter_id: int,
    source_type: str,
    version: int,
    data_dir: str | Path = "data",
    reason: str = "user_archived_version",
) -> dict[str, Any]:
    _validate_source_type(source_type)
    if chapter_id < 1:
        raise VersionArchiveError("chapter_id must be >= 1")
    if version < 1:
        raise VersionArchiveError("version must be >= 1")

    root = Path(data_dir)
    versions = list_versions(chapter_id, root)
    match = _find_version(versions, source_type, version)
    if not match:
        raise VersionArchiveError(f"chapter_{format_chapter_id(chapter_id)} {source_type}:v{version:03d} not found.")

    archive_root = root / "archive" / "versions" / f"chapter_{format_chapter_id(chapter_id)}" / f"{source_type}_v{version:03d}"
    sources = _version_related_files(root, match, chapter_id, source_type, version)
    if not sources:
        raise VersionArchiveError(f"chapter_{format_chapter_id(chapter_id)} {source_type}:v{version:03d} has no local files to archive.")

    moved: list[tuple[Path, Path]] = []
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = archive_root / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            moved.append((source, target))

        meta = {
            "chapter": chapter_id,
            "source_type": source_type,
            "version": version,
            "version_label": match.get("version_label", f"{source_type}_v{version:03d}"),
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "files": [
                {"source": source.relative_to(root).as_posix(), "archived_path": target.relative_to(archive_root).as_posix()}
                for source, target in moved
            ],
        }
        _write_json_atomic(archive_root / "archive_meta.json", meta)

        next_versions = list_versions(chapter_id, root)
        save_versions_index(chapter_id, next_versions, root)
    except Exception:
        _rollback_moves(moved)
        raise

    return {
        "chapter_id": chapter_id,
        "source_type": source_type,
        "version": version,
        "archive_dir": archive_root.as_posix(),
        "archive_meta_path": (archive_root / "archive_meta.json").as_posix(),
        "files": meta["files"],
        "selected": next_versions.get("selected", {}),
    }


def get_selected_version(chapter_id: int, data_dir: str | Path = "data") -> dict[str, Any]:
    versions = load_versions_index(chapter_id, data_dir)
    selected = versions.get("selected", {})
    if isinstance(selected, dict) and selected.get("source_type") and selected.get("version"):
        match = _find_version(versions, str(selected["source_type"]), int(selected["version"]))
        if match:
            return match

    manual = versions.get("manual", [])
    if manual:
        return manual[-1]
    edited = versions.get("edited", [])
    if edited:
        return edited[-1]
    drafts = versions.get("drafts", [])
    if drafts:
        return drafts[-1]
    return {}


def read_version_payload(version_info: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(version_info.get("json_path", "")))
    if not path.exists():
        raise FileNotFoundError(path.as_posix())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_path"] = path.as_posix()
    payload["json_path"] = path.as_posix()
    return payload


def _scan_kind(root: Path, chapter_id: int, kind: str) -> list[dict[str, Any]]:
    directory = root / _directory_name(kind)
    if not directory.exists():
        return []
    chapter_code = format_chapter_id(chapter_id)
    pattern = re.compile(rf"^chapter_{chapter_code}_{kind}_v(\d{{3}})\.json$")
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"chapter_{chapter_code}_{kind}_v*.json")):
        match = pattern.match(path.name)
        if not match:
            continue
        version = int(match.group(1))
        payload = _safe_read_json(path)
        if not payload:
            continue
        text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text", ""))
        process = payload.get("editing", {}) if kind in {"edited", "manual"} else payload.get("generation", {})
        info = {
            "source_type": kind,
            "version": version,
            "version_label": str(payload.get("version_label", f"{kind}_v{version:03d}")),
            "json_path": path.as_posix(),
            "markdown_path": path.with_suffix(".md").as_posix(),
            "chapter_id": int(payload.get("chapter_id", chapter_id) or chapter_id),
            "chapter_title": str(payload.get("chapter_title", "")),
            "created_at": str(payload.get("created_at", "")),
            "actual_word_count": int(payload.get("actual_word_count", len(text)) or 0),
            "mode": str(process.get("mode", "")) if isinstance(process, dict) else "",
            "fallback_used": bool(process.get("fallback_used", False)) if isinstance(process, dict) else False,
            "preview": text[:300],
        }
        if kind == "edited":
            info["source_draft_version"] = int(payload.get("source_draft_version", 0) or 0)
        if kind == "manual":
            info["source_origin_type"] = str(payload.get("source_type", ""))
            info["source_origin_version"] = int(payload.get("source_version", 0) or 0)
        result.append(info)
    return sorted(result, key=lambda item: int(item.get("version", 0) or 0))


def _find_version(versions: dict[str, Any], source_type: str, version: int) -> dict[str, Any]:
    _validate_source_type(source_type)
    for item in versions.get(_collection_key(source_type), []):
        if int(item.get("version", 0) or 0) == version and Path(str(item.get("json_path", ""))).exists():
            return item
    return {}


def _find_version_in_lists(
    drafts: list[dict[str, Any]],
    edited: list[dict[str, Any]],
    manual: list[dict[str, Any]],
    selected: dict[str, Any],
) -> bool:
    source_type = str(selected.get("source_type", ""))
    try:
        version = int(selected.get("version", 0) or 0)
    except (TypeError, ValueError):
        return False
    collection = drafts if source_type == "draft" else manual if source_type == "manual" else edited
    return any(int(item.get("version", 0) or 0) == version for item in collection)


def _version_related_files(
    root: Path,
    match: dict[str, Any],
    chapter_id: int,
    source_type: str,
    version: int,
) -> list[Path]:
    sources: list[Path] = []
    for key in ["json_path", "markdown_path"]:
        path = Path(str(match.get(key, "")))
        if path.exists() and path.is_file():
            sources.append(path)
    quality_stem = f"chapter_{chapter_id:03d}_{source_type}_v{version:03d}_quality"
    continuity_stem = f"chapter_{chapter_id:03d}_{source_type}_v{version:03d}_continuity"
    for directory, stem in [("quality_reports", quality_stem), ("continuity_reports", continuity_stem)]:
        for suffix in [".json", ".md"]:
            path = root / directory / f"{stem}{suffix}"
            if path.exists() and path.is_file():
                sources.append(path)
    return sorted(set(sources), key=lambda path: path.as_posix())


def _rollback_moves(moved: list[tuple[Path, Path]]) -> None:
    for source, target in reversed(moved):
        if target.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            target.replace(source)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _read_index_if_exists(chapter_id: int, root: Path) -> dict[str, Any]:
    path = _index_path(chapter_id, root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (PermissionError, FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (PermissionError, FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _index_path(chapter_id: int, root: Path) -> Path:
    return root / "versions" / f"chapter_{format_chapter_id(chapter_id)}_versions.json"


def _directory_name(kind: str) -> str:
    if kind == "draft":
        return "drafts"
    if kind == "manual":
        return "manual"
    return "edited"


def _collection_key(kind: str) -> str:
    if kind == "draft":
        return "drafts"
    if kind == "manual":
        return "manual"
    return "edited"


def _validate_source_type(source_type: str) -> None:
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"非法版本类型：{source_type}")


def _path_mtime(path: str) -> str:
    target = Path(path)
    if not target.exists():
        return ""
    return str(int(target.stat().st_mtime))
