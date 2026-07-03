from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FORESHADOW_KEYWORDS = ["发送失败", "异常", "秘密", "未知", "隐藏", "钩子"]


def commit_chapter(
    draft: dict[str, Any],
    chapter_plan: dict[str, Any],
    state: dict[str, Any],
    story_spec: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
) -> dict[str, Any]:
    chapter_id = int(draft.get("chapter_id", chapter_plan.get("chapter_id", 1)) or 1)
    chapter_title = str(draft.get("chapter_title", chapter_plan.get("chapter_title", "")))
    chapter_path = _chapter_path(chapter_id)
    summary_path = _summary_path(chapter_id)
    source_used = "manual" if draft.get("manual_text") else ("edited" if draft.get("edited_text") else "draft")
    source_version = int(draft.get("source_version", draft.get("version", 0)) or 0)
    source_path = str(draft.get("source_path", draft.get("json_path", draft.get("source_draft_path", ""))))
    warnings: list[str] = []
    if chapter_path.exists():
        warnings.append("正式章节文件已存在，本次已覆盖。")

    summary = summarize_chapter(draft, chapter_plan)
    state_patch = apply_state_updates(state, chapter_plan, summary)
    update_memory_index(summary, chapter_path.as_posix(), summary_path.as_posix())

    return {
        "commit_version": "1.2",
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "status": "committed",
        "source_used": source_used,
        "source_version": source_version,
        "source_path": source_path,
        "chapter_path": chapter_path.as_posix(),
        "summary_path": summary_path.as_posix(),
        "memory_updated": True,
        "state_updated": True,
        "summary": summary,
        "state_patch": state_patch,
        "warnings": warnings,
    }


def summarize_chapter(draft: dict[str, Any], chapter_plan: dict[str, Any]) -> dict[str, Any]:
    chapter_text = _chapter_text(draft)
    chapter_id = int(draft.get("chapter_id", chapter_plan.get("chapter_id", 1)) or 1)
    chapter_title = str(draft.get("chapter_title", chapter_plan.get("chapter_title", "")))
    chapter_goal = str(chapter_plan.get("chapter_goal", ""))
    main_conflict = str(chapter_plan.get("conflict_design", {}).get("main_conflict", ""))
    climax_event = str(chapter_plan.get("climax_design", {}).get("climax_event", ""))
    key_events = [item for item in [chapter_goal, main_conflict, climax_event] if item]
    characters_involved = chapter_plan.get("required_context", {}).get("characters_to_use", [])
    world_rules_used = chapter_plan.get("required_context", {}).get("world_rules_to_use", [])
    foreshadows = _foreshadows_from_text_and_plan(chapter_text, chapter_plan)

    return {
        "summary_version": "1.2",
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "short_summary": _short_summary(chapter_title, key_events, chapter_text),
        "key_events": key_events,
        "characters_involved": characters_involved,
        "world_rules_used": world_rules_used,
        "new_information": _new_information(chapter_plan),
        "foreshadows_planted": foreshadows,
        "foreshadows_touched": [],
        "state_changes": {
            "characters": _character_state_changes(characters_involved),
            "world": {"rules_used": world_rules_used},
            "plot": {"completed_events": key_events},
            "timeline": [_timeline_entry(chapter_id, chapter_title, key_events)],
        },
        "memory_tags": _memory_tags(chapter_plan, foreshadows),
    }


def apply_state_updates(
    state: dict[str, Any],
    chapter_plan: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    chapter_id = int(chapter_plan.get("chapter_id", summary.get("chapter_id", 1)) or 1)
    chapter_title = str(chapter_plan.get("chapter_title", summary.get("chapter_title", "")))
    chapter_path = _chapter_path(chapter_id).as_posix()
    summary_path = _summary_path(chapter_id).as_posix()

    state["current_chapter"] = chapter_id
    state["current_stage"] = "chapter_committed"
    plot = state.setdefault("plot", {})
    completed_events = plot.setdefault("completed_events", [])
    for event in summary.get("key_events", []):
        if event and event not in completed_events:
            completed_events.append(event)

    foreshadows = state.setdefault("foreshadows", [])
    _append_unique_foreshadows(foreshadows, summary.get("foreshadows_planted", []), chapter_id)

    timeline = state.setdefault("timeline", [])
    timeline_entry = _timeline_entry(chapter_id, chapter_title, summary.get("key_events", []))
    if timeline_entry not in timeline:
        timeline.append(timeline_entry)

    state_characters = state.setdefault("characters", {})
    for character in summary.get("characters_involved", []):
        name = str(character.get("name", character.get("id", "")))
        if not name:
            continue
        original = state_characters.setdefault(name, {})
        original.setdefault("physical", "保持原状态")
        original["mental"] = "经历本章事件后更加警觉"
        original["goal"] = "继续推进当前目标"

    state["last_committed_chapter"] = {
        "chapter_id": chapter_id,
        "title": chapter_title,
        "chapter_path": chapter_path,
        "summary_path": summary_path,
    }
    if isinstance(state.get("draft"), dict):
        state["draft"]["status"] = "committed"
    if isinstance(state.get("edited"), dict):
        state["edited"]["status"] = "committed"

    return {
        "current_chapter": chapter_id,
        "current_stage": "chapter_committed",
        "completed_events_added": summary.get("key_events", []),
        "foreshadows_added": summary.get("foreshadows_planted", []),
        "timeline_added": timeline_entry,
    }


def update_memory_index(summary: dict[str, Any], chapter_path: str, summary_path: str) -> dict[str, Any]:
    memory_path = Path("data/memory/memory_index.json")
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    if memory_path.exists():
        memory_index = json.loads(memory_path.read_text(encoding="utf-8"))
    else:
        memory_index = {
            "memory_version": "0.6",
            "working_context_chapters": 3,
            "chapters": [],
        }

    chapter_entry = {
        "chapter_id": summary.get("chapter_id", 1),
        "title": summary.get("chapter_title", ""),
        "chapter_path": chapter_path,
        "summary_path": summary_path,
        "memory_tags": summary.get("memory_tags", []),
        "short_summary": summary.get("short_summary", ""),
    }
    chapters = memory_index.setdefault("chapters", [])
    for index, existing in enumerate(chapters):
        if existing.get("chapter_id") == chapter_entry["chapter_id"]:
            chapters[index] = chapter_entry
            break
    else:
        chapters.append(chapter_entry)

    memory_path.write_text(json.dumps(memory_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return memory_index


def render_committed_chapter_markdown(draft: dict[str, Any]) -> str:
    chapter_id = int(draft.get("chapter_id", 1) or 1)
    chapter_title = str(draft.get("chapter_title", ""))
    return f"# 第{chapter_id}章 {chapter_title}\n\n{_chapter_text(draft)}\n"


def _chapter_text(draft: dict[str, Any]) -> str:
    return str(draft.get("manual_text") or draft.get("edited_text") or draft.get("draft_text", ""))


def _chapter_path(chapter_id: int) -> Path:
    return Path("data/chapters") / f"chapter_{chapter_id:03d}.md"


def _summary_path(chapter_id: int) -> Path:
    return Path("data/summaries") / f"chapter_{chapter_id:03d}_summary.json"


def _short_summary(chapter_title: str, key_events: list[str], chapter_text: str) -> str:
    event_text = "；".join(key_events[:3]) or "本章推进当前章计划。"
    excerpt = chapter_text.replace("\n", "")[:120]
    return f"《{chapter_title}》围绕{event_text}展开。正文中，角色在既定世界观规则限制下处理当前压力，并留下可追踪的状态变化。片段线索：{excerpt}"


def _new_information(chapter_plan: dict[str, Any]) -> list[str]:
    phase = chapter_plan.get("phase_position", {})
    return [f"当前位于阶段：{phase.get('phase_title', '')}"]


def _foreshadows_from_text_and_plan(draft_text: str, chapter_plan: dict[str, Any]) -> list[dict[str, str]]:
    combined = draft_text + json.dumps(chapter_plan, ensure_ascii=False)
    planted = []
    for keyword in FORESHADOW_KEYWORDS:
        if keyword in combined:
            planted.append({"content": f"与“{keyword}”相关的未解信息需要后续回收", "importance": "medium"})
    if not planted:
        planted.append({"content": "本章结尾钩子需要后续回收", "importance": "medium"})
    return planted[:3]


def _character_state_changes(characters: Any) -> dict[str, dict[str, str]]:
    if not isinstance(characters, list):
        return {}
    changes = {}
    for character in characters:
        name = str(character.get("name", character.get("id", "")))
        if name:
            changes[name] = {
                "physical": "保持原状态",
                "mental": "经历本章事件后更加警觉",
                "goal": "继续推进当前目标",
            }
    return changes


def _timeline_entry(chapter_id: int, chapter_title: str, key_events: Any) -> dict[str, Any]:
    event = key_events[0] if isinstance(key_events, list) and key_events else "本章事件已提交"
    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "event": event,
        "time_note": "未明确时间",
    }


def _append_unique_foreshadows(foreshadows: list[Any], planted: Any, chapter_id: int) -> None:
    existing_contents = {item.get("content") for item in foreshadows if isinstance(item, dict)}
    next_id = _next_foreshadow_id(foreshadows)
    if not isinstance(planted, list):
        return
    for item in planted:
        content = str(item.get("content", "")) if isinstance(item, dict) else str(item)
        if not content or content in existing_contents:
            continue
        foreshadows.append(
            {
                "id": f"fs_{next_id:03d}",
                "content": content,
                "status": "open",
                "introduced_at": f"chapter_{chapter_id:03d}",
                "importance": item.get("importance", "medium") if isinstance(item, dict) else "medium",
            }
        )
        existing_contents.add(content)
        next_id += 1


def _next_foreshadow_id(foreshadows: list[Any]) -> int:
    max_id = 0
    for item in foreshadows:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id", ""))
        if raw_id.startswith("fs_") and raw_id[3:].isdigit():
            max_id = max(max_id, int(raw_id[3:]))
    return max_id + 1


def _memory_tags(chapter_plan: dict[str, Any], foreshadows: list[dict[str, str]]) -> list[str]:
    tags = ["chapter", "committed"]
    phase = chapter_plan.get("phase_position", {})
    if phase.get("phase_title"):
        tags.append(str(phase["phase_title"]))
    if foreshadows:
        tags.append("foreshadow")
    return tags
