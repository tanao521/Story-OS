"""Read-only anchor and source projections for rolling planning."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore

from .models import content_hash
from .source_service import SourceService
from .version_service import VersionService


def _chapter_numbers(context: ProjectContext) -> list[int]:
    values: list[int] = []
    for path in context.chapters_dir.glob("chapter_*.md"):
        match = re.fullmatch(r"chapter_(\d+)\.md", path.name)
        if match:
            values.append(int(match.group(1)))
    return sorted(set(values))


def resolve_planning_anchor(context: ProjectContext) -> dict[str, Any]:
    store = DataStore(context)
    state = store.read_json(context.data_dir / "state.json", default={}, expected_type=dict) or {}
    chapters = _chapter_numbers(context)
    last_canon = chapters[-1] if chapters else 0
    warnings: list[str] = []
    raw_state = state.get("current_chapter")
    try:
        state_chapter = int(raw_state)
    except (TypeError, ValueError):
        state_chapter = None
        warnings.append("state.current_chapter 缺失或无效；锚点按已提交章节推导。")
    if state_chapter is not None and state_chapter != last_canon:
        warnings.append("state.current_chapter 与已提交章节不一致；未自动修改状态文件。")
    if chapters and chapters != list(range(1, last_canon + 1)):
        warnings.append("已提交章节编号不连续；滚动窗口仅作为人工规划意图。")
    blueprint = store.read_json(context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}
    versions = VersionService(context).list()
    canon_version_id = _latest_canon_version(context, last_canon)
    return {"next_chapter_number": last_canon + 1, "last_canon_chapter_number": last_canon, "last_canon_version_id": canon_version_id, "state_hash": content_hash(state), "blueprint_hash": content_hash(blueprint), "planning_control_version_id": versions[0]["version_id"] if versions else "", "warnings": warnings}


def blueprint_slot_suggestions(context: ProjectContext, anchor: dict[str, Any], count: int) -> list[dict[str, Any]]:
    store = DataStore(context)
    blueprint = store.read_json(context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}
    chapter_plan = blueprint.get("chapter_plan", []) if isinstance(blueprint.get("chapter_plan"), list) else []
    start, end = int(anchor["next_chapter_number"]), int(anchor["next_chapter_number"]) + count - 1
    source = SourceService(context)
    result = []
    for item in chapter_plan:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("chapter_id", item.get("chapter_number", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if start <= number <= end:
            summary = {key: item.get(key) for key in ("chapter_title", "chapter_goal", "phase_position", "conflict_design") if item.get(key) not in (None, "", {}, [])}
            result.append({"planned_chapter_number": number, "summary": summary, "source_ref": source.ref("story_blueprint", "data/story_blueprint.json", "chapter_plan", str(number), value=item)})
    return result


def far_horizon_projection(context: ProjectContext, control: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
    blueprint = SourceService(context).blueprint_projection()
    phases = blueprint.get("story_phases", [])
    phase_ref: dict[str, Any] = {}
    chapter_suggestions = blueprint_slot_suggestions(context, anchor, 1)
    phase_position = (chapter_suggestions[0].get("summary", {}).get("phase_position", {}) if chapter_suggestions else {})
    if isinstance(phase_position, dict) and phase_position.get("phase_id") not in (None, ""):
        phase_ref = {"source_type": "story_blueprint", "entity_type": "story_phase", "entity_id": str(phase_position["phase_id"]), "display_name": phase_position.get("phase_title", "")}
    elif phases and isinstance(phases[0], dict):
        phase_ref = {"source_type": "story_blueprint", "entity_type": "story_phase", "entity_id": str(phases[0].get("phase_id", phases[0].get("id", ""))), "display_name": phases[0].get("title", "")}
    phase_contracts = [item for item in control.get("phase_contracts", []) if item.get("phase_ref") == phase_ref]
    open_milestones = [item.get("milestone_id", item.get("id")) for item in control.get("milestones", []) if item.get("status") not in {"achieved", "cancelled", "replaced"}]
    return {"scope_type": "phase" if phase_ref else "project", "scope_ref": phase_ref, "direction_summary": (control.get("strategy") or {}).get("story_promise", ""), "required_milestone_ids": open_milestones, "required_volume_contract_items": [item.get("contract_id", item.get("id")) for item in control.get("volume_contracts", [])], "required_phase_contract_items": [item.get("contract_id", item.get("id")) for item in phase_contracts], "preserve_elements": [], "open_questions": [], "author_notes": "", "source_refs": [blueprint.get("source_ref", {})]}


def _latest_canon_version(context: ProjectContext, chapter: int) -> str:
    if chapter < 1:
        return ""
    index = DataStore(context).read_json(context.data_dir / "canon_versions" / f"chapter_{chapter:03d}" / "index.json", default={}, expected_type=dict) or {}
    return str(index.get("current_version_id", ""))
