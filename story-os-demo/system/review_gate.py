from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from system.version_manager import get_selected_version, load_versions_index


VALID_REVIEW_STATUSES = {"pending", "approved", "rejected"}


def find_current_review_target(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    plan_path = root / "next_chapter_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError("缺少 data/next_chapter_plan.json，无法确定当前审核章节。")
    plan = _read_json(plan_path)
    chapter_id = int(plan.get("chapter_id", 1) or 1)
    chapter_title = str(plan.get("chapter_title", ""))

    selected = get_selected_version(chapter_id, root)
    if selected:
        payload = _read_json(Path(selected["json_path"]))
        return _target_from_payload(
            root,
            chapter_id,
            chapter_title,
            str(selected.get("source_type", "")),
            Path(selected["json_path"]),
            payload,
            selected,
        )

    edited_json = root / "edited" / f"chapter_{chapter_id:03d}_edited.json"
    draft_json = root / "drafts" / f"chapter_{chapter_id:03d}_draft.json"
    if edited_json.exists():
        payload = _read_json(edited_json)
        return _target_from_payload(root, chapter_id, chapter_title, "edited", edited_json, payload, {})
    if draft_json.exists():
        payload = _read_json(draft_json)
        return _target_from_payload(root, chapter_id, chapter_title, "draft", draft_json, payload, {})
    raise FileNotFoundError("未找到当前章编辑版或草稿，请先运行 write-draft / edit-draft。")


def create_review_record(target: dict[str, Any], status: str = "pending") -> dict[str, Any]:
    _validate_status(status)
    now = _now()
    return {
        "review_version": "1.5",
        "chapter_id": int(target.get("chapter_id", 1) or 1),
        "chapter_title": str(target.get("chapter_title", "")),
        "source_type": str(target.get("source_type", "")),
        "source_version": int(target.get("version", 0) or 0),
        "version_label": str(target.get("version_label", "")),
        "source_path": str(target.get("json_path", "")),
        "status": status,
        "decision": "",
        "review_notes": "",
        "created_at": now,
        "updated_at": now,
    }


def save_review_record(record: dict[str, Any], data_dir: str | Path = "data") -> str:
    chapter_id = int(record.get("chapter_id", 1) or 1)
    path = Path(data_dir) / "reviews" / f"chapter_{chapter_id:03d}_review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.as_posix()


def load_review_record(chapter_id: int, data_dir: str | Path = "data") -> dict[str, Any]:
    path = Path(data_dir) / "reviews" / f"chapter_{chapter_id:03d}_review.json"
    if not path.exists():
        return {}
    return _read_json(path)


def update_review_status(
    chapter_id: int,
    status: str,
    decision: str = "",
    notes: str = "",
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    _validate_status(status)
    record = load_review_record(chapter_id, data_dir)
    if not record:
        target = find_current_review_target(data_dir)
        record = create_review_record(target)
    record["status"] = status
    record["decision"] = decision
    record["review_notes"] = notes
    record["updated_at"] = _now()
    save_review_record(record, data_dir)
    return record


def render_review_markdown(record: dict[str, Any], target: dict[str, Any]) -> str:
    preview = str(target.get("text", ""))[:1500]
    return f"""# 第{record.get("chapter_id", "")}章审核记录

## 审核状态

- 状态：{record.get("status", "")}
- 来源：{record.get("source_type", "")}
- 版本：{record.get("version_label", "") or target.get("version_label", "")}
- 文件：{record.get("source_path", "")}
- 创建时间：{record.get("created_at", "")}
- 更新时间：{record.get("updated_at", "")}

## 正文预览

{preview}

## 审核意见

{record.get("review_notes", "") or "无"}
"""


def save_review_markdown(
    record: dict[str, Any],
    target: dict[str, Any],
    data_dir: str | Path = "data",
) -> str:
    chapter_id = int(record.get("chapter_id", 1) or 1)
    path = Path(data_dir) / "reviews" / f"chapter_{chapter_id:03d}_review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_markdown(record, target), encoding="utf-8")
    return path.as_posix()


def prepare_review_record(data_dir: str | Path = "data") -> dict[str, Any]:
    target = find_current_review_target(data_dir)
    record = load_review_record(int(target["chapter_id"]), data_dir)
    if not record:
        record = create_review_record(target)
    else:
        record["source_type"] = target.get("source_type", record.get("source_type", ""))
        record["source_version"] = int(target.get("version", record.get("source_version", 0)) or 0)
        record["version_label"] = target.get("version_label", record.get("version_label", ""))
        record["source_path"] = target.get("json_path", record.get("source_path", ""))
    json_path = save_review_record(record, data_dir)
    markdown_path = save_review_markdown(record, target, data_dir)
    return {
        "target": target,
        "record": record,
        "json_path": json_path,
        "markdown_path": markdown_path,
    }


def review_versions(chapter_id: int, data_dir: str | Path = "data") -> dict[str, Any]:
    return load_versions_index(chapter_id, data_dir)


def _target_from_payload(
    root: Path,
    chapter_id: int,
    chapter_title: str,
    source_type: str,
    json_path: Path,
    payload: dict[str, Any],
    version_info: dict[str, Any],
) -> dict[str, Any]:
    markdown_path = json_path.with_suffix(".md")
    text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text", ""))
    return {
        "chapter_id": chapter_id,
        "chapter_title": str(payload.get("chapter_title", chapter_title)),
        "source_type": source_type,
        "version": int(version_info.get("version", payload.get("version", 0)) or 0),
        "version_label": str(version_info.get("version_label", payload.get("version_label", ""))),
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
        "text": text,
        "relative_source_path": json_path.relative_to(root).as_posix(),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_status(status: str) -> None:
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"非法审核状态：{status}")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
