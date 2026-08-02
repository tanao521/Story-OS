from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from system.version_manager import get_selected_version, load_versions_index
from core.project_context import get_project_context
from system.review_decision_service import (
    capture_identity,
    content_fingerprint,
    create_decision,
)


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
        "content_fingerprint": content_fingerprint(str(target.get("text", ""))),
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
    authoritative_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_status(status)
    record = load_review_record(chapter_id, data_dir)
    target: dict[str, Any] | None = None
    try:
        target = find_current_review_target(data_dir)
    except FileNotFoundError:
        target = None
    if not record:
        if target is None:
            raise FileNotFoundError("无法确定当前审核版本")
        record = create_review_record(target)

    # The legacy chapter review JSON remains a compatibility projection.  When
    # an authoritative source file is available, every terminal human decision
    # is additionally persisted in the append-only, exact-version decision log.
    if status in {"approved", "rejected"} and target is not None:
        source_path = Path(str(target.get("json_path") or ""))
        if not source_path.is_absolute():
            data_root = Path(data_dir).resolve()
            project_root = data_root.parent if data_root.name == "data" else data_root
            source_path = project_root / source_path
        if source_path.exists() and int(target.get("version", 0) or 0) >= 1 and target.get("version_label"):
            root = Path(data_dir).resolve()
            project_root = root.parent if root.name == "data" else root
            identity = capture_identity(get_project_context(project_root), target)
            decision_record = authoritative_decision or create_decision(
                get_project_context(project_root), identity,
                "APPROVED" if status == "approved" else "REJECTED", note=notes,
            )
            record["review_decision_id"] = decision_record["decision_id"]
            record["review_identity"] = decision_record["identity"]
            record["content_fingerprint"] = identity.content_fingerprint
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
        current_fingerprint = content_fingerprint(str(target.get("text", "")))
        same_identity = (
            record.get("source_type") == target.get("source_type")
            and record.get("version_label") == target.get("version_label")
            and record.get("content_fingerprint") == current_fingerprint
        )
        if not same_identity:
            # Never retarget a prior approval/rejection to a newly selected or
            # edited work version.  Start a fresh compatibility projection;
            # durable authority is stored by review_decision_service.
            record = create_review_record(target)
        else:
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
