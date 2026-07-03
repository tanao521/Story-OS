from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


VALID_SOURCE_TYPES = {"draft", "edited", "manual"}


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
    return {
        "version_index": "1.5",
        "chapter_id": chapter_id,
        "drafts": _scan_kind(root, chapter_id, "draft"),
        "edited": _scan_kind(root, chapter_id, "edited"),
        "manual": _scan_kind(root, chapter_id, "manual"),
        "selected": existing.get("selected", {}) if isinstance(existing.get("selected"), dict) else {},
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


def _read_index_if_exists(chapter_id: int, root: Path) -> dict[str, Any]:
    path = _index_path(chapter_id, root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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
