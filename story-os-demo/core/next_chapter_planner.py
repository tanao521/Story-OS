from __future__ import annotations

from typing import Any


STATE_SNAPSHOT_KEYS = [
    "current_chapter",
    "current_stage",
    "characters",
    "world",
    "plot",
    "foreshadows",
    "memory_policy",
]

STATE_UPDATES_EXPECTED = [
    "更新 current_chapter",
    "记录本章完成事件",
    "更新角色心理状态",
    "记录新增伏笔或已触发伏笔",
    "生成本章摘要供后续记忆系统使用",
]


def plan_next_chapter(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_chapter = int(state.get("current_chapter", 0) or 0)
    chapter_id = current_chapter + 1
    phase = _select_phase(blueprint.get("story_phases", []), current_chapter)
    selected_characters = _select_characters(characters, chapter_id)
    selected_rules = _select_world_rules(world_bible)
    genre_tendency = _genre_tendency(str(story_spec.get("genre", "")))
    climax_design = _climax_design(chapter_id)

    return {
        "plan_version": "0.4",
        "chapter_id": chapter_id,
        "chapter_title": _chapter_title(chapter_id, phase, genre_tendency),
        "estimated_word_count": _estimated_word_count(story_spec),
        "chapter_goal": _chapter_goal(chapter_id, phase, genre_tendency),
        "phase_position": {
            "phase_id": phase.get("phase_id", 1),
            "phase_title": phase.get("title", ""),
            "reason": _phase_reason(current_chapter, phase),
        },
        "required_context": {
            "recent_chapters": [],
            "state_snapshot": _state_snapshot(state),
            "characters_to_use": selected_characters,
            "world_rules_to_use": selected_rules,
            "foreshadows_to_consider": _open_foreshadows(state),
            "memory_context_used": working_context is not None,
        },
        "scene_plan": _scene_plan(chapter_id, selected_characters, world_bible, genre_tendency),
        "conflict_design": _conflict_design(story_spec, phase, genre_tendency),
        "pacing_design": _pacing_design(chapter_id),
        "climax_design": climax_design,
        "voice_requirements": _voice_requirements(characters, selected_characters),
        "style_requirements": _style_requirements(story_spec),
        "continuity_constraints": _continuity_constraints(world_bible),
        "state_updates_expected": STATE_UPDATES_EXPECTED.copy(),
    }


def render_next_chapter_plan_markdown(plan: dict[str, Any]) -> str:
    return f"""# 下一章计划：第{plan.get("chapter_id", "")}章 {plan.get("chapter_title", "")}

## 章节目标

{plan.get("chapter_goal", "")}

## 当前阶段

- 阶段：{plan.get("phase_position", {}).get("phase_id", "")}：{plan.get("phase_position", {}).get("phase_title", "")}
- 原因：{plan.get("phase_position", {}).get("reason", "")}

## 必要上下文

- 登场角色：{_names(plan.get("required_context", {}).get("characters_to_use", []))}
- 世界规则：{_rules(plan.get("required_context", {}).get("world_rules_to_use", []))}
- 伏笔：{_foreshadows(plan.get("required_context", {}).get("foreshadows_to_consider", []))}

## 场景计划

{_render_scenes(plan.get("scene_plan", []))}

## 冲突设计

{_render_mapping(plan.get("conflict_design", {}))}

## 节奏设计

{_render_mapping(plan.get("pacing_design", {}))}

## 高潮设计

{_render_mapping(plan.get("climax_design", {}))}

## 角色声音要求

{_render_mapping(plan.get("voice_requirements", {}))}

## 文风要求

{_render_list(plan.get("style_requirements", []))}

## 连续性约束

{_render_list(plan.get("continuity_constraints", []))}

## 写完后预计更新

{_render_list(plan.get("state_updates_expected", []))}
"""


def _select_phase(phases: Any, current_chapter: int) -> dict[str, Any]:
    if not isinstance(phases, list) or not phases:
        return {"phase_id": 1, "title": "开局", "purpose": "建立下一章行动方向"}

    if current_chapter < 5:
        index = 0
    elif current_chapter < 15:
        index = 1
    elif current_chapter < 30:
        index = 2
    else:
        index = min(len(phases) - 1, max(0, current_chapter // 15))
    return phases[min(index, len(phases) - 1)]


def _select_characters(characters: dict[str, Any], chapter_id: int) -> list[dict[str, Any]]:
    main_characters = characters.get("main_characters", [])
    if not isinstance(main_characters, list) or not main_characters:
        return []
    count = 1 if chapter_id == 1 else min(3, len(main_characters))
    return [
        {
            "id": character.get("id", ""),
            "name": character.get("name", ""),
            "role": character.get("role", ""),
        }
        for character in main_characters[:count]
    ]


def _select_world_rules(world_bible: dict[str, Any]) -> list[dict[str, str]]:
    rules = world_bible.get("core_rules", [])
    if not isinstance(rules, list):
        return []
    return [
        {
            "id": rule.get("id", ""),
            "rule": rule.get("rule", ""),
            "story_function": rule.get("story_function", ""),
        }
        for rule in rules[:3]
    ]


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state.get(key) for key in STATE_SNAPSHOT_KEYS if key in state}


def _open_foreshadows(state: dict[str, Any]) -> list[dict[str, Any]]:
    foreshadows = state.get("foreshadows", [])
    if not isinstance(foreshadows, list):
        return []
    return [
        item
        for item in foreshadows
        if isinstance(item, dict) and item.get("status") in {"open", "planned"}
    ]


def _scene_plan(
    chapter_id: int,
    selected_characters: list[dict[str, Any]],
    world_bible: dict[str, Any],
    tendency: dict[str, str],
) -> list[dict[str, Any]]:
    locations = world_bible.get("locations", [])
    character_names = [character.get("name", "") for character in selected_characters]
    if chapter_id == 1:
        scene_titles = ["开场建立处境", "发现问题或压力", "留下钩子"]
    else:
        scene_titles = ["承接上章状态", "推进本章压力", "形成新的选择"]

    return [
        {
            "scene_id": index,
            "scene_title": title,
            "purpose": _scene_purpose(index, title),
            "location": _location_name(locations, index),
            "characters": character_names,
            "conflict": tendency["conflict"],
            "emotional_beat": _emotional_beat(index),
            "must_include": [tendency["must_include"], "不要写成正文，只作为后续 Writer 的计划约束"],
        }
        for index, title in enumerate(scene_titles, start=1)
    ]


def _conflict_design(
    story_spec: dict[str, Any],
    phase: dict[str, Any],
    tendency: dict[str, str],
) -> dict[str, str]:
    return {
        "main_conflict": tendency["conflict"],
        "secondary_conflict": f"角色目标与阶段任务“{phase.get('title', '')}”之间出现信息差。",
        "pressure_source": tendency["pressure"],
        "choice_pressure": f"必须在{_join(story_spec.get('focus', []))}与当前安全之间做取舍。",
    }


def _pacing_design(chapter_id: int) -> dict[str, Any]:
    if chapter_id == 1:
        return {
            "pacing_type": "开局建立",
            "emotion_curve": ["陌生", "压抑", "紧张", "悬念"],
            "action_ratio": 30,
            "dialogue_ratio": 40,
            "description_ratio": 30,
            "ending_hook": "强钩子：让主角意识到处境比想象更糟。",
        }
    if chapter_id % 10 == 0:
        pacing_type = "中高潮"
    elif chapter_id % 5 == 0:
        pacing_type = "小高潮"
    else:
        pacing_type = "推进"
    return {
        "pacing_type": pacing_type,
        "emotion_curve": ["承压", "试探", "推进", "余波"],
        "action_ratio": 35,
        "dialogue_ratio": 35,
        "description_ratio": 30,
        "ending_hook": "留下下一章必须处理的新问题。",
    }


def _climax_design(chapter_id: int) -> dict[str, str]:
    if chapter_id == 1:
        return {
            "climax_level": "minor",
            "climax_event": "主角发现处境比想象更糟",
            "state_change_after_climax": "主角从被动醒来到主动确认生存压力",
        }
    if chapter_id % 10 == 0:
        return {
            "climax_level": "medium",
            "climax_event": "阶段性矛盾集中爆发",
            "state_change_after_climax": "角色关系、资源或主线判断发生中等变化",
        }
    if chapter_id % 5 == 0:
        return {
            "climax_level": "minor",
            "climax_event": "小规模压力爆发",
            "state_change_after_climax": "角色获得新信息或付出轻量代价",
        }
    return {
        "climax_level": "none",
        "climax_event": "不设置明显高潮，重点推进信息和关系",
        "state_change_after_climax": "记录轻量状态变化",
    }


def _voice_requirements(
    characters: dict[str, Any],
    selected_characters: list[dict[str, Any]],
) -> dict[str, Any]:
    profiles = {}
    main_characters = characters.get("main_characters", [])
    for selected in selected_characters:
        for character in main_characters:
            if character.get("id") == selected.get("id"):
                profiles[character.get("name", "")] = character.get("voice_profile", {})
                break
    return {
        "global_dialogue_rules": characters.get("voice_rules", {}).get("global_dialogue_rules", []),
        "character_voice_profiles": profiles,
    }


def _style_requirements(story_spec: dict[str, Any]) -> list[str]:
    requirements = [f"文笔风格：{story_spec.get('writing_style', '')}"]
    requirements.extend(f"去 AI 味规则：{rule}" for rule in _as_list(story_spec.get("anti_ai_style_rules", [])))
    requirements.extend(f"禁止内容或不想要的风格：{rule}" for rule in _as_list(story_spec.get("avoid", [])))
    return requirements


def _continuity_constraints(world_bible: dict[str, Any]) -> list[str]:
    rules = _as_list(world_bible.get("continuity_rules", []))
    required = [
        "人物知道的信息不能超过其经历范围",
        "资源、时间、伤势、关系变化必须持续记录",
        "写作时必须遵守已建立世界规则",
    ]
    return list(dict.fromkeys(required + rules))


def _genre_tendency(genre: str) -> dict[str, str]:
    if "末世" in genre:
        return {
            "conflict": "资源压力、通讯中断和未知异常同时逼近",
            "pressure": "避难所或地下空间中的生存压力",
            "must_include": "人物互相试探，外部威胁只露出一角",
        }
    if "玄幻" in genre or "修仙" in genre:
        return {
            "conflict": "规则展示、能力限制和势力关系形成压力",
            "pressure": "初始修行压力与传承线索",
            "must_include": "明确能力不能无代价使用",
        }
    if "都市" in genre:
        return {
            "conflict": "现实压力、身份矛盾和关系变化互相挤压",
            "pressure": "职场、家庭或身份责任",
            "must_include": "推进一个小目标，同时暴露关系张力",
        }
    if "悬疑" in genre:
        return {
            "conflict": "线索出现、误导和异常细节制造新问题",
            "pressure": "信息差与时间压力",
            "must_include": "结尾留下可追踪的悬念",
        }
    return {
        "conflict": "人物目标和外部阻力发生正面碰撞",
        "pressure": "环境限制和关系变化",
        "must_include": "用具体行动推动下一章目标",
    }


def _chapter_title(chapter_id: int, phase: dict[str, Any], tendency: dict[str, str]) -> str:
    if chapter_id == 1:
        return "醒来的压力"
    return f"{phase.get('title', '下一阶段')}中的新问题"


def _chapter_goal(chapter_id: int, phase: dict[str, Any], tendency: dict[str, str]) -> str:
    if chapter_id == 1:
        return f"建立主角处境，展示{tendency['pressure']}，并在结尾留下强钩子。"
    return f"推进“{phase.get('title', '')}”阶段目标，让{tendency['conflict']}带来新的状态变化。"


def _phase_reason(current_chapter: int, phase: dict[str, Any]) -> str:
    return f"current_chapter={current_chapter}，按滚动式阶段估算落在“{phase.get('title', '')}”。"


def _estimated_word_count(story_spec: dict[str, Any]) -> int:
    length_type = str(story_spec.get("length_type", "长篇"))
    if length_type == "短篇":
        return 2000
    if length_type == "中篇":
        return 2500
    return 3000


def _scene_purpose(index: int, title: str) -> str:
    purposes = {
        1: "建立本章初始状态和行动压力",
        2: "让问题具体化，并推动角色做出反应",
        3: "改变信息状态，留下下一步必须处理的钩子",
        4: "整理余波并设置下一章入口",
    }
    return purposes.get(index, title)


def _location_name(locations: Any, index: int) -> str:
    if isinstance(locations, list) and locations:
        item = locations[(index - 1) % len(locations)]
        if isinstance(item, dict):
            return str(item.get("name", ""))
    return "待定地点"


def _emotional_beat(index: int) -> str:
    beats = ["陌生和压迫", "紧张和试探", "悬念和余波", "短暂喘息"]
    return beats[(index - 1) % len(beats)]


def _render_scenes(scenes: Any) -> str:
    if not isinstance(scenes, list) or not scenes:
        return "无"
    return "\n\n".join(
        f"""### 场景{scene.get("scene_id", "")}：{scene.get("scene_title", "")}

- 作用：{scene.get("purpose", "")}
- 地点：{scene.get("location", "")}
- 登场角色：{_join(scene.get("characters", []))}
- 冲突：{scene.get("conflict", "")}
- 情绪节拍：{scene.get("emotional_beat", "")}
- 必须包含：{_join(scene.get("must_include", []))}"""
        for scene in scenes
    )


def _render_mapping(mapping: Any) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "无"
    lines = []
    for key, value in mapping.items():
        if isinstance(value, list):
            rendered = _join(value)
        elif isinstance(value, dict):
            rendered = "; ".join(f"{inner_key}: {inner_value}" for inner_key, inner_value in value.items())
        else:
            rendered = str(value)
        lines.append(f"- {key}：{rendered}")
    return "\n".join(lines)


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _names(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "、".join(str(item.get("name", "")) for item in items if isinstance(item, dict))


def _rules(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "、".join(str(item.get("rule", "")) for item in items if isinstance(item, dict))


def _foreshadows(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "、".join(str(item.get("id", item.get("content", ""))) for item in items if isinstance(item, dict))


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _join(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "、".join(str(item) for item in items)
