from __future__ import annotations

from typing import Any


GLOBAL_DIALOGUE_RULES = [
    "不同角色说话方式必须区分",
    "避免所有角色使用同一种解释型语气",
    "情绪优先通过停顿、动作、短句体现",
]

ANTI_AI_DIALOGUE_RULES = [
    "减少‘不是A，而是B’句式",
    "减少破折号",
    "避免角色长篇解释世界观",
    "避免每句台词都过于完整",
]

GENRE_ROLE_TENDENCIES = {
    "末世": ["生存者", "秩序建立者", "情绪不稳定者", "资源掌控者", "隐瞒秘密者", "外部威胁见证者"],
    "玄幻": ["修行者", "师长", "同辈竞争者", "宗门/家族代表", "神秘传承相关者", "未来敌人"],
    "修仙": ["修行者", "师长", "同辈竞争者", "宗门/家族代表", "神秘传承相关者", "未来敌人"],
    "都市": ["主角本人", "现实压力来源", "亲密关系角色", "职场/家庭关系角色", "价值观冲突者"],
    "悬疑": ["调查者", "关键证人", "误导者", "隐瞒秘密者", "真相相关者"],
}


def generate_characters(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    structure = str(story_spec.get("character_structure", "单男主"))
    main_count, support_count, gender_plan = _character_counts(structure)
    genre_roles = _genre_roles(str(story_spec.get("genre", "")))
    main_characters = [
        _build_main_character(index, story_spec, blueprint, genre_roles, gender_plan)
        for index in range(1, main_count + 1)
    ]
    supporting_characters = [
        _build_supporting_character(index, story_spec, genre_roles, main_characters)
        for index in range(1, support_count + 1)
    ]

    return {
        "characters_version": "0.3",
        "character_structure": structure,
        "main_characters": main_characters,
        "supporting_characters": supporting_characters,
        "relationship_map": _relationship_map(main_characters, supporting_characters),
        "voice_rules": {
            "global_dialogue_rules": GLOBAL_DIALOGUE_RULES.copy(),
            "anti_ai_dialogue_rules": ANTI_AI_DIALOGUE_RULES.copy(),
        },
    }


def render_characters_markdown(characters: dict[str, Any]) -> str:
    main_sections = "\n\n".join(
        _render_main_character(character)
        for character in characters.get("main_characters", [])
    )
    supporting_sections = "\n\n".join(
        _render_supporting_character(character)
        for character in characters.get("supporting_characters", [])
    )
    relationship_lines = _render_relationships(characters.get("relationship_map", []))
    voice_rules = characters.get("voice_rules", {})

    return f"""# 角色卡

## 主角

{main_sections}

## 配角

{supporting_sections}

## 人物关系图

{relationship_lines}

## 对话规则

### 全局规则
{_render_list(voice_rules.get("global_dialogue_rules", []))}

### 去 AI 味规则
{_render_list(voice_rules.get("anti_ai_dialogue_rules", []))}
"""


def _character_counts(structure: str) -> tuple[int, int, list[str]]:
    if structure in {"单男主", "单女主"}:
        return 1, 3, ["男" if structure == "单男主" else "女"]
    if structure == "男女双主角":
        return 2, 3, ["男", "女"]
    if structure == "群像文":
        return 4, 4, ["男", "女", "女", "男"]
    if structure == "多女主单男主":
        return 4, 3, ["男", "女", "女", "女"]
    if structure == "多男主单女主":
        return 4, 3, ["女", "男", "男", "男"]
    if structure == "无固定主角":
        return 5, 3, ["未知", "未知", "未知", "未知", "未知"]
    return 2, 3, ["未知", "未知"]


def _genre_roles(genre: str) -> list[str]:
    for keyword, roles in GENRE_ROLE_TENDENCIES.items():
        if keyword in genre:
            return roles
    return ["行动者", "协助者", "阻碍者", "秘密持有者", "关系推动者"]


def _build_main_character(
    index: int,
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    genre_roles: list[str],
    gender_plan: list[str],
) -> dict[str, Any]:
    role = genre_roles[(index - 1) % len(genre_roles)]
    name = f"主角{index}"
    gender = gender_plan[(index - 1) % len(gender_plan)]
    world_style = story_spec.get("world_style", "")
    main_arc = blueprint.get("main_arc", "")
    focus = _join(story_spec.get("focus", []))
    return {
        "id": f"char_{index:03d}",
        "name": name,
        "role": role,
        "gender": gender,
        "age": "待定",
        "appearance": f"带有{world_style}环境留下的明显痕迹，细节后续逐章补充。",
        "personality": ["警觉", "有执念", "会在压力下改变策略"],
        "core_desire": f"在{focus}中找到可持续的行动位置。",
        "core_fear": "失去选择权，或让重要关系被局势吞没。",
        "external_goal": f"沿着主线推进：{main_arc}",
        "internal_conflict": "想掌控局势，却必须承认自己掌握的信息有限。",
        "background": f"与{world_style}和核心冲突有关，保留关键空白供后续逐章揭示。",
        "current_state": {
            "physical": "可行动，但资源和体力都需要持续记录",
            "mental": "警惕、压抑，仍保留行动意志",
            "resources": ["基础生存资源", "少量可信关系"],
            "knowledge": ["知道当前阶段目标", "不了解隐藏真相全貌"],
        },
        "relationships": {},
        "voice_profile": {
            "tone": _voice_tone(index),
            "sentence_length": "短句为主，关键时刻允许中句",
            "speech_habits": ["先判断局势，再表达态度", "避免长篇解释"],
            "forbidden_expressions": ["让我总结一下", "这说明了什么"],
        },
    }


def _build_supporting_character(
    index: int,
    story_spec: dict[str, Any],
    genre_roles: list[str],
    main_characters: list[dict[str, Any]],
) -> dict[str, Any]:
    role = genre_roles[(index + len(main_characters) - 1) % len(genre_roles)]
    main_name = main_characters[0]["name"] if main_characters else "主角"
    return {
        "id": f"char_{100 + index:03d}",
        "name": f"配角{index}",
        "role": role,
        "function_in_story": f"推动{story_spec.get('genre', '故事')}类型中的阶段性冲突或信息差。",
        "personality": ["立场明确", "有隐瞒", "与主线保持张力"],
        "relationship_to_main": f"与{main_name}存在合作、试探或利益冲突。",
        "secret_or_conflict": "掌握一部分信息，但不会一次性说出。",
        "voice_profile": {
            "tone": "谨慎",
            "sentence_length": "中短句",
            "speech_habits": ["回避直接回答", "用具体事实代替解释"],
        },
    }


def _relationship_map(
    main_characters: list[dict[str, Any]],
    supporting_characters: list[dict[str, Any]],
) -> list[dict[str, str]]:
    relationships = []
    all_characters = main_characters + supporting_characters
    if len(main_characters) >= 2:
        relationships.append(
            {
                "from": main_characters[0]["id"],
                "to": main_characters[1]["id"],
                "relationship": "共同主线承担者",
                "tension": "目标一致但方法不同",
                "possible_change": "从互相试探转为有限信任",
            }
        )
    for character in all_characters[1:4]:
        relationships.append(
            {
                "from": main_characters[0]["id"],
                "to": character["id"],
                "relationship": "关键互动关系",
                "tension": "信息不对称",
                "possible_change": "随阶段推进转向合作或对抗",
            }
        )
    return relationships


def _render_main_character(character: dict[str, Any]) -> str:
    state = character.get("current_state", {})
    voice = character.get("voice_profile", {})
    return f"""### {character.get("id", "")}：{character.get("name", "")}

- 角色定位：{character.get("role", "")}
- 年龄：{character.get("age", "")}
- 外貌：{character.get("appearance", "")}
- 性格：{_join(character.get("personality", []))}
- 核心欲望：{character.get("core_desire", "")}
- 核心恐惧：{character.get("core_fear", "")}
- 外部目标：{character.get("external_goal", "")}
- 内部冲突：{character.get("internal_conflict", "")}
- 当前状态：身体：{state.get("physical", "")}；心理：{state.get("mental", "")}
- 语言风格：{voice.get("tone", "")}，{voice.get("sentence_length", "")}"""


def _render_supporting_character(character: dict[str, Any]) -> str:
    return f"""### {character.get("id", "")}：{character.get("name", "")}

- 角色定位：{character.get("role", "")}
- 故事功能：{character.get("function_in_story", "")}
- 性格：{_join(character.get("personality", []))}
- 与主角关系：{character.get("relationship_to_main", "")}
- 秘密或冲突：{character.get("secret_or_conflict", "")}"""


def _render_relationships(relationships: Any) -> str:
    if not isinstance(relationships, list) or not relationships:
        return "无"
    return "\n".join(
        f"- {item.get('from', '')} -> {item.get('to', '')}：{item.get('relationship', '')}；张力：{item.get('tension', '')}；变化：{item.get('possible_change', '')}"
        for item in relationships
    )


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _join(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "待定"
    return "、".join(str(item) for item in items)


def _voice_tone(index: int) -> str:
    tones = ["克制", "直接", "试探", "冷静", "带刺"]
    return tones[(index - 1) % len(tones)]
