from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


BLUEPRINT_VERSION = "v1.0"


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "novel_title", "novelTitle", "project_name", "projectName"),
    "novel_type": ("novel_type", "novelType", "genre", "type"),
    "custom_type": ("custom_type", "customType", "custom_genre", "customGenre"),
    "length": ("length", "length_type", "lengthType"),
    "target_words": ("target_words", "targetWords", "target_word_count", "targetWordCount"),
    "pov": ("pov", "narration", "narrative_pov", "narrativePov"),
    "character_structure": ("character_structure", "characterStructure"),
    "romance_intensity": ("romance_intensity", "romanceIntensity", "romance_level", "romanceLevel"),
    "tone": ("tone", "overall_tone", "overallTone"),
    "prose_style": ("prose_style", "proseStyle", "writing_style", "writingStyle"),
    "world_style": ("world_style", "worldStyle"),
    "plot_focus": ("plot_focus", "plotFocus", "focus"),
    "forbidden_content": ("forbidden_content", "forbiddenContent", "avoid"),
    "ai_style_limits": ("ai_style_limits", "aiStyleLimits", "anti_ai_style_rules", "antiAiStyleRules"),
}


def resolve_current_project_root(
    project_name: str | None = None,
    project_root: str | Path | None = None,
) -> Path:
    if project_root is not None:
        return Path(project_root).expanduser().resolve()
    if project_name:
        return (Path.cwd() / "projects" / project_name).resolve()
    active_project = _active_project_from_local_config(Path.cwd())
    if active_project:
        return active_project.resolve()
    return Path.cwd().resolve()


def ensure_project_structure(project_root: Path, form_data: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    data_dir = root / "data"
    chapters_dir = root / "chapters"
    logs_dir = root / "logs"
    for directory in (data_dir, chapters_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    events: list[str] = []
    config_path = data_dir / "project_config.json"
    story_spec_path = data_dir / "story_spec.json"
    blueprint_path = data_dir / "story_blueprint.json"
    plot_state_path = data_dir / "plot_state.json"
    chapter_index_path = data_dir / "chapter_index.json"
    characters_path = data_dir / "characters.json"
    world_rules_path = data_dir / "world_rules.json"
    world_bible_path = data_dir / "world_bible.json"

    source_data = _source_form_data(form_data, story_spec_path, config_path)
    _ensure_project_config(config_path, root, source_data, events)
    _ensure_blueprint(blueprint_path, config_path, source_data, events)
    _ensure_file(plot_state_path, _default_plot_state(), events, "plot_state.json created")
    _ensure_file(chapter_index_path, {"chapters": []}, events, "chapter_index.json created")
    _ensure_file(characters_path, {"characters": [], "main_characters": []}, events, "characters.json created")
    _ensure_file(world_rules_path, {"rules": [], "locations": [], "organizations": [], "power_system": {}}, events, "world_rules.json created")
    _ensure_file(world_bible_path, _default_world_bible(source_data), events, "world_bible.json created")
    _ensure_gitkeep(chapters_dir)
    _log_project_event(logs_dir, f"[project] project_root = {root}")
    _log_project_event(logs_dir, f"[project] data_dir = {data_dir}")
    _log_project_event(logs_dir, f"[project] blueprint_path = {blueprint_path}")
    _log_project_event(logs_dir, f"[project] plot_state_path = {plot_state_path}")
    _log_project_event(logs_dir, f"[project] chapter_index_path = {chapter_index_path}")
    for event in events:
        _log_project_event(logs_dir, f"[project] {event}")
        print(f"[project] {event}")

    return {
        "project_root": root,
        "data_dir": data_dir,
        "blueprint_path": blueprint_path,
        "config_path": config_path,
        "plot_state_path": plot_state_path,
        "chapter_index_path": chapter_index_path,
        "characters_path": characters_path,
        "world_rules_path": world_rules_path,
        "world_bible_path": world_bible_path,
        "story_spec_path": story_spec_path,
        "events": events,
    }


def build_story_blueprint_from_form(
    form_data: dict[str, Any],
    project_root: Path | None = None,
) -> dict[str, Any]:
    title = _get_text(form_data, "title") or "未命名小说"
    novel_type = _get_text(form_data, "novel_type") or "其他"
    custom_type = _get_text(form_data, "custom_type")
    length = _get_text(form_data, "length") or "长篇"
    target_words = _get_int(form_data, "target_words", _default_target_words(length))
    pov = _get_text(form_data, "pov")
    character_structure = _get_text(form_data, "character_structure")
    romance_intensity = _get_text(form_data, "romance_intensity")
    tone = _get_text(form_data, "tone")
    prose_style = _get_text(form_data, "prose_style")
    world_style = _get_text(form_data, "world_style")
    plot_focus = _get_list(form_data, "plot_focus")
    forbidden_content = _get_list(form_data, "forbidden_content")
    ai_style_limits = _get_list(form_data, "ai_style_limits")
    effective_type = custom_type if novel_type in {"其他", "自定义", "other", "Other"} and custom_type else novel_type
    phases = _story_phases(length, target_words)
    focus_text = "、".join(plot_focus[:3]) if plot_focus else "核心冲突与人物选择"
    return {
        "project_meta": {
            "project_name": title,
            "version": BLUEPRINT_VERSION,
            "language": "zh-CN",
            "status": "initialized",
            "project_root": str(project_root.resolve()) if project_root else "",
        },
        "basic_settings": {
            "title": title,
            "novel_type": novel_type,
            "custom_type": custom_type,
            "length": length,
            "target_words": target_words,
            "one_sentence_hook": f"{title}围绕{focus_text}展开。",
        },
        "narrative_settings": {
            "pov": pov,
            "character_structure": character_structure,
            "romance_intensity": romance_intensity,
            "overall_tone": tone,
            "prose_style": prose_style,
        },
        "world_and_plot": {
            "world_style": world_style,
            "plot_focus": plot_focus,
            "forbidden_content": forbidden_content,
            "ai_style_limits": ai_style_limits,
        },
        "core_rules": {
            "genre_definition": effective_type,
            "reality_rule": world_style,
            "conflict_rule": focus_text,
        },
        "character_bible": {
            "protagonist": {},
            "key_characters": [],
        },
        "volume_plan": [],
        "chapter_plan": [],
        "generation_rules": {
            "chapter_length": _chapter_length_label(length),
            "must_follow": plot_focus,
            "must_avoid": forbidden_content + ai_style_limits,
        },
        "title": title,
        "blueprint_version": "0.2-compatible",
        "genre": effective_type,
        "length_type": length,
        "target_word_count": target_words,
        "core_premise": f"以{world_style or '当前世界观'}为基础，推动{focus_text}。",
        "main_arc": f"{character_structure or '主角'}在{effective_type}框架中逐步面对{focus_text}。",
        "core_conflict": focus_text,
        "ending_direction": "保持逐章滚动生成，不预写完整结局细节。",
        "world_direction": {
            "world_style": world_style,
            "rules_to_explore": plot_focus,
            "important_locations": [],
            "hidden_truths": [],
        },
        "story_phases": phases,
        "initial_foreshadow_pool": [],
        "rolling_generation_policy": {
            "mode": "chapter_by_chapter",
            "plan_next_chapter_only": True,
            "working_context_chapters": 3,
            "older_chapters_strategy": "summarize_and_retrieve",
            "state_update_after_each_chapter": True,
        },
    }


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc.msg}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _active_project_from_local_config(root: Path) -> Path | None:
    config_path = root / ".story_os" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = config.get("active_project") if isinstance(config, dict) else None
    if not value:
        return None
    return Path(str(value)).expanduser()


def _source_form_data(
    form_data: dict[str, Any] | None,
    story_spec_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    if form_data:
        return dict(form_data)
    story_spec = read_json(story_spec_path, None)
    if isinstance(story_spec, dict) and story_spec:
        return story_spec
    config = read_json(config_path, None)
    if isinstance(config, dict):
        raw = config.get("raw_form_data")
        if isinstance(raw, dict) and raw:
            return raw
        return config
    return {}


def _ensure_project_config(path: Path, root: Path, source_data: dict[str, Any], events: list[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    existing = _read_json_with_backup(path, default={}, events=events)
    if not isinstance(existing, dict):
        existing = {}
    created_at = str(existing.get("created_at") or now)
    config = {
        **existing,
        "project_name": _get_text(source_data, "title") or existing.get("project_name", ""),
        "created_at": created_at,
        "updated_at": now,
        "project_root": str(root),
        "active": True,
    }
    if source_data:
        config["raw_form_data"] = source_data
    write_json(path, config)
    events.append("project_config.json updated")


def _ensure_blueprint(
    path: Path,
    config_path: Path,
    source_data: dict[str, Any],
    events: list[str],
) -> None:
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            events.append("story_blueprint.json loaded")
            return
        except json.JSONDecodeError:
            backup = _backup_broken_json(path)
            events.append(f"story_blueprint.json was broken; backed up to {backup.name}")
    data = source_data
    source_label = "form data"
    if not data:
        config = read_json(config_path, {})
        if isinstance(config, dict):
            raw = config.get("raw_form_data")
            data = raw if isinstance(raw, dict) else config
            source_label = "project_config.json"
    blueprint = build_story_blueprint_from_form(data or {}, path.parents[1])
    write_json(path, blueprint)
    events.append(f"story_blueprint.json created from {source_label}")


def _ensure_file(path: Path, default_data: dict[str, Any], events: list[str], event: str) -> None:
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return
        except json.JSONDecodeError:
            backup = _backup_broken_json(path)
            events.append(f"{path.name} was broken; backed up to {backup.name}")
    write_json(path, default_data)
    events.append(event)


def _read_json_with_backup(path: Path, default: Any, events: list[str]) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = _backup_broken_json(path)
        events.append(f"{path.name} was broken; backed up to {backup.name}")
        return default


def _backup_broken_json(path: Path) -> Path:
    backup = path.with_name(f"{path.stem}.broken{path.suffix}")
    if backup.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup = path.with_name(f"{path.stem}.broken.{stamp}{path.suffix}")
    path.replace(backup)
    return backup


def _ensure_gitkeep(directory: Path) -> None:
    marker = directory / ".gitkeep"
    if not marker.exists():
        marker.write_text("", encoding="utf-8")


def _log_project_event(logs_dir: Path, message: str) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    (logs_dir / "generation.log").open("a", encoding="utf-8").write(f"[{timestamp}] {message}\n")


def _default_plot_state() -> dict[str, Any]:
    return {
        "current_volume": 1,
        "current_chapter": 0,
        "last_chapter_title": "",
        "last_chapter_summary": "",
        "current_arc": "",
        "open_threads": [],
        "resolved_threads": [],
        "character_state_changes": [],
        "world_state_changes": [],
        "next_chapter_goal": "",
    }


def _default_world_bible(source_data: dict[str, Any]) -> dict[str, Any]:
    world_style = _get_text(source_data, "world_style")
    plot_focus = _get_list(source_data, "plot_focus")
    return {
        "world_bible_version": "minimal-lifecycle",
        "world_style": world_style,
        "core_rules": [
            {
                "id": "rule_001",
                "rule": item,
                "story_function": "来自项目初始化表单的剧情重点。",
            }
            for item in plot_focus[:3]
        ],
        "locations": [],
        "power_or_system": {},
        "social_order": {},
        "resources": {},
        "taboos_or_limits": _get_list(source_data, "forbidden_content"),
        "hidden_truths": [],
        "sensory_style": {},
        "continuity_rules": [
            "保持逐章滚动生成。",
            "不得跳过人工审核。",
            "新增设定必须回写记忆。",
        ],
    }


def _story_phases(length: str, target_words: int) -> list[dict[str, Any]]:
    if length == "短篇":
        titles = ["开端", "转折", "收束"]
    elif length == "中篇":
        titles = ["开局", "发展", "危机", "终局"]
    else:
        titles = ["开局与规则建立", "关系扩张与初级对抗", "真相逼近与秩序崩坏", "主线爆发与重大反转", "终局重构"]
    average = target_words // len(titles) if target_words > 0 else 0
    return [
        {
            "phase_id": index,
            "title": title,
            "purpose": f"{title}阶段用于支撑后续逐章规划。",
            "estimated_word_range": f"约{int(average * 0.8)}~{int(average * 1.2)}字" if average else "待定",
            "main_conflicts": [],
            "character_changes": [],
            "foreshadows_to_plant": [],
            "foreshadows_to_payoff": [],
        }
        for index, title in enumerate(titles, start=1)
    ]


def _get_text(data: dict[str, Any], key: str) -> str:
    for alias in FIELD_ALIASES[key]:
        value = data.get(alias)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _get_int(data: dict[str, Any], key: str, default: int) -> int:
    for alias in FIELD_ALIASES[key]:
        value = data.get(alias)
        if value in (None, ""):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        return parsed if parsed > 0 else default
    return default


def _get_list(data: dict[str, Any], key: str) -> list[str]:
    for alias in FIELD_ALIASES[key]:
        if alias not in data:
            continue
        value = data.get(alias)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        normalized = str(value).replace("，", ",").replace("\n", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def _default_target_words(length: str) -> int:
    return {"短篇": 8000, "中篇": 60000, "长篇": 300000, "超长篇": 1000000}.get(length, 300000)


def _chapter_length_label(length: str) -> str:
    if length == "短篇":
        return "1500-3000"
    if length == "中篇":
        return "2500-5000"
    return "3000-6000"
