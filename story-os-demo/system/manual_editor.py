from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from system.version_manager import (
    build_versioned_paths,
    get_next_version_number,
    list_versions,
    read_version_payload,
    save_versions_index,
    select_version,
)


TEXT_FIELD_BY_TYPE = {
    "draft": "draft_text",
    "edited": "edited_text",
    "manual": "manual_text",
}


def count_text_chars(text: str) -> int:
    return len(text.strip())


def is_valid_manual_text(text: str, min_chars: int = 200) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    stripped = text.strip()
    if not stripped:
        warnings.append("manual text is empty")
    if stripped and count_text_chars(stripped) < min_chars:
        warnings.append("manual text is too short")
    if _looks_like_json(stripped):
        warnings.append("manual text looks like JSON")
    if "作为AI" in stripped or "作为 AI" in stripped:
        warnings.append("manual text contains AI self-reference")
    if "我无法" in stripped:
        warnings.append("manual text contains refusal phrase")
    if _looks_like_instruction_only(stripped):
        warnings.append("manual text looks like instructions, not prose")
    return not warnings, warnings


def load_source_version_text(
    chapter_id: int,
    source_type: str,
    version: int,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    if source_type not in TEXT_FIELD_BY_TYPE:
        raise ValueError(f"unsupported source_type: {source_type}")
    versions = list_versions(chapter_id, data_dir)
    collection_key = "drafts" if source_type == "draft" else source_type
    match = {}
    for item in versions.get(collection_key, []):
        if int(item.get("version", 0) or 0) == version:
            match = item
            break
    if not match:
        raise FileNotFoundError(f"chapter_{chapter_id:03d} {source_type}:{version} not found")
    payload = read_version_payload(match)
    text_field = TEXT_FIELD_BY_TYPE[source_type]
    text = str(payload.get(text_field) or payload.get("text", ""))
    return {
        "chapter_id": int(payload.get("chapter_id", chapter_id) or chapter_id),
        "chapter_title": str(payload.get("chapter_title", "")),
        "source_type": source_type,
        "version": version,
        "version_label": str(match.get("version_label", payload.get("version_label", f"{source_type}_v{version:03d}"))),
        "text": text,
        "json_path": str(match.get("json_path", "")),
        "markdown_path": str(match.get("markdown_path", "")),
    }


def create_manual_version(
    chapter_id: int,
    source_type: str,
    source_version: int,
    manual_text: str,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    valid, warnings = is_valid_manual_text(manual_text)
    if not valid:
        raise ValueError("; ".join(warnings))

    source = load_source_version_text(chapter_id, source_type, source_version, data_dir)
    version = get_next_version_number(chapter_id, "manual", data_dir)
    paths = build_versioned_paths(chapter_id, "manual", version, data_dir)
    now = _now()
    manual = {
        "manual_version": "2.3",
        "chapter_id": chapter_id,
        "chapter_title": source.get("chapter_title", ""),
        "status": "manual",
        "version": version,
        "version_label": f"manual_v{version:03d}",
        "source_type": source_type,
        "source_version": source_version,
        "source_path": source.get("json_path", ""),
        "manual_text": manual_text,
        "actual_word_count": count_text_chars(manual_text),
        "created_at": now,
        "updated_at": now,
        "editing": {
            "mode": "manual",
            "model": "human",
            "fallback_used": False,
            "warnings": [],
        },
        "checks": {
            "valid_text": True,
            "warnings": warnings,
        },
    }

    json_path = Path(paths["json_path"])
    markdown_path = Path(paths["markdown_path"])
    latest_json_path = Path(data_dir) / "manual" / f"chapter_{chapter_id:03d}_manual.json"
    latest_markdown_path = Path(data_dir) / "manual" / f"chapter_{chapter_id:03d}_manual.md"
    markdown = render_manual_markdown(manual)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    latest_json_path.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_markdown_path.write_text(markdown, encoding="utf-8")

    versions = list_versions(chapter_id, data_dir)
    save_versions_index(chapter_id, versions, data_dir)
    selected = select_version(chapter_id, "manual", version, data_dir)

    return {
        "chapter_id": chapter_id,
        "source_type": "manual",
        "version": version,
        "version_label": manual["version_label"],
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
        "latest_json_path": latest_json_path.as_posix(),
        "latest_markdown_path": latest_markdown_path.as_posix(),
        "selected": bool(selected),
        "source": {
            "source_type": source_type,
            "source_version": source_version,
            "source_path": source.get("json_path", ""),
        },
        "manual": manual,
    }


def render_manual_markdown(manual: dict[str, Any]) -> str:
    chapter_id = int(manual.get("chapter_id", 1) or 1)
    chapter_title = str(manual.get("chapter_title", ""))
    label = str(manual.get("version_label", "manual_v000"))
    source_type = str(manual.get("source_type", ""))
    source_version = int(manual.get("source_version", 0) or 0)
    checks = manual.get("checks", {})
    warnings = checks.get("warnings", []) if isinstance(checks, dict) else []
    warning_rows = "\n".join(f"- {item}" for item in warnings) or "- none"
    return f"""# 第{chapter_id}章 {chapter_title}（人工修改版 {label}）

## 状态

- 版本：v2.3
- 状态：manual
- 来源：{source_type}_v{source_version:03d}
- 实际字数：{manual.get("actual_word_count", 0)}
- 创建时间：{manual.get("created_at", "")}

## 正文

{manual.get("manual_text", "")}

## 检查

- valid_text: {checks.get("valid_text", False) if isinstance(checks, dict) else False}
{warning_rows}
"""


def _looks_like_json(text: str) -> bool:
    if not text:
        return False
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _looks_like_instruction_only(text: str) -> bool:
    if not text:
        return False
    instruction_terms = ["请", "生成", "改写", "润色", "大纲", "要求", "不要", "需要"]
    prose_marks = ["。", "！", "？", "“", "”", "\n"]
    instruction_hits = sum(1 for term in instruction_terms if term in text[:300])
    has_prose_marks = any(mark in text for mark in prose_marks)
    return instruction_hits >= 3 and not has_prose_marks


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
