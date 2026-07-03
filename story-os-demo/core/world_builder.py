from __future__ import annotations

from typing import Any


CONTINUITY_RULES = [
    "写作时必须遵守已建立世界规则",
    "新增设定必须写入 world_bible",
    "禁止突然引入未铺垫的解决方案",
    "人物知道的信息不能超过其经历范围",
    "资源、时间、伤势、关系变化必须持续记录",
]


def generate_world_bible(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    genre = str(story_spec.get("genre", "其他"))
    world_style = str(story_spec.get("world_style", ""))
    world_direction = blueprint.get("world_direction", {})
    rules = _text_list(world_direction.get("rules_to_explore", []))
    locations = _text_list(world_direction.get("important_locations", []))
    hidden_truths = _text_list(world_direction.get("hidden_truths", []))

    return {
        "world_bible_version": "0.3",
        "world_style": world_style,
        "genre": genre,
        "core_rules": _core_rules(rules, genre),
        "locations": _locations(locations, genre),
        "power_or_system": _power_or_system(genre, rules),
        "social_order": _social_order(genre, world_style),
        "resources": _resources(genre),
        "taboos_or_limits": _taboos_or_limits(genre),
        "hidden_truths": hidden_truths or ["核心真相后续逐章揭示，不在 v0.3 展开成章节。"],
        "sensory_style": _sensory_style(genre, world_style),
        "continuity_rules": CONTINUITY_RULES.copy(),
    }


def render_world_bible_markdown(world_bible: dict[str, Any]) -> str:
    return f"""# 世界观设定集

## 世界风格

- 类型：{world_bible.get("genre", "")}
- 风格：{world_bible.get("world_style", "")}

## 核心规则

{_render_rules(world_bible.get("core_rules", []))}

## 重要地点

{_render_locations(world_bible.get("locations", []))}

## 系统 / 能力 / 社会规则

{_render_mapping(world_bible.get("power_or_system", {}))}

## 社会秩序

{_render_mapping(world_bible.get("social_order", {}))}

## 资源系统

{_render_mapping(world_bible.get("resources", {}))}

## 禁忌与限制

{_render_list(world_bible.get("taboos_or_limits", []))}

## 隐藏真相

{_render_list(world_bible.get("hidden_truths", []))}

## 感官风格

{_render_mapping(world_bible.get("sensory_style", {}))}

## 连续性规则

{_render_list(world_bible.get("continuity_rules", []))}
"""


def _core_rules(rule_names: list[str], genre: str) -> list[dict[str, str]]:
    if not rule_names:
        rule_names = ["核心规则", "代价规则", "冲突升级规则"]
    return [
        {
            "id": f"rule_{index:03d}",
            "rule": rule,
            "description": f"{genre}故事中必须持续遵守的设定边界。",
            "story_function": "限制角色行动，制造可追踪的选择成本。",
        }
        for index, rule in enumerate(rule_names, start=1)
    ]


def _locations(location_names: list[str], genre: str) -> list[dict[str, str]]:
    if not location_names:
        location_names = ["故事起点", "主要冲突场域", "终局场域"]
    danger_levels = ["中", "高", "未知"]
    return [
        {
            "id": f"loc_{index:03d}",
            "name": name,
            "type": f"{genre}关键地点",
            "description": "承载阶段目标、人物关系变化和伏笔回收的场所。",
            "story_function": "为后续逐章计划提供稳定空间锚点。",
            "danger_level": danger_levels[(index - 1) % len(danger_levels)],
        }
        for index, name in enumerate(location_names, start=1)
    ]


def _power_or_system(genre: str, rules: list[str]) -> dict[str, Any]:
    base_rules = rules or ["行动必须付出代价", "解决方案必须提前铺垫"]
    if "末世" in genre:
        return {
            "type": "避难所系统 / 生存规则 / 资源限制",
            "rules": base_rules,
            "limitations": ["资源不可凭空增加", "伤势和疲劳需要持续记录"],
            "costs": ["信任成本", "物资成本", "时间成本"],
        }
    if "玄幻" in genre or "修仙" in genre:
        return {
            "type": "修行体系 / 境界体系",
            "levels": ["入门", "进阶", "破境", "瓶颈", "重构"],
            "rules": base_rules,
            "limitations": ["突破需要条件", "力量增长必须有代价"],
            "costs": ["资源消耗", "心性风险", "因果牵连"],
        }
    if "都市" in genre:
        return {
            "type": "现实社会规则 / 职业系统 / 关系网络",
            "rules": base_rules,
            "limitations": ["社会身份限制行动", "关系变化会带来连锁后果"],
            "costs": ["时间成本", "机会成本", "关系成本"],
        }
    if "悬疑" in genre:
        return {
            "type": "线索系统 / 调查规则",
            "rules": base_rules,
            "limitations": ["线索不能凭空出现", "角色推理不能超过已知信息"],
            "costs": ["误判成本", "暴露风险", "时间压力"],
        }
    return {
        "type": "通用故事规则系统",
        "rules": base_rules,
        "limitations": ["新增设定必须回写", "关键解决方案必须提前铺垫"],
        "costs": ["行动成本", "关系成本", "信息成本"],
    }


def _social_order(genre: str, world_style: str) -> dict[str, Any]:
    return {
        "dominant_order": f"{world_style}中的显性秩序",
        "pressure_sources": _genre_pressures(genre),
        "conflict_pattern": "个体目标与环境规则互相挤压，逐章升级。",
    }


def _resources(genre: str) -> dict[str, Any]:
    if "末世" in genre:
        return {"scarce": ["食物", "药品", "安全空间"], "tracked": ["物资", "伤势", "信任"]}
    if "玄幻" in genre or "修仙" in genre:
        return {"scarce": ["灵气", "功法", "传承资格"], "tracked": ["修为", "资源", "因果"]}
    if "悬疑" in genre:
        return {"scarce": ["线索", "时间", "可信证词"], "tracked": ["证据", "嫌疑", "角色已知信息"]}
    return {"scarce": ["时间", "机会", "关系支持"], "tracked": ["金钱", "身份", "承诺"]}


def _taboos_or_limits(genre: str) -> list[str]:
    limits = ["禁止突然引入未铺垫的解决方案", "禁止让角色知道超出经历范围的信息"]
    if "末世" in genre:
        limits.append("资源不能无代价恢复")
    if "悬疑" in genre:
        limits.append("真相不能早于关键线索完整出现")
    return limits


def _sensory_style(genre: str, world_style: str) -> dict[str, list[str]]:
    return {
        "visual": [world_style or "清晰可追踪的场景", "反复出现的环境细节"],
        "sound": ["远处噪声", "人物停顿", "环境变化声"],
        "smell": ["潮湿", "尘土", "封闭空间的气味"],
        "texture": ["粗糙", "冰冷", "磨损"],
        "atmosphere": [_genre_atmosphere(genre), "克制，不用解释性旁白替代细节"],
    }


def _genre_pressures(genre: str) -> list[str]:
    if "末世" in genre:
        return ["资源不足", "外部威胁", "临时秩序"]
    if "玄幻" in genre or "修仙" in genre:
        return ["境界差距", "势力规训", "传承代价"]
    if "都市" in genre:
        return ["身份压力", "职业压力", "关系责任"]
    if "悬疑" in genre:
        return ["信息差", "误导", "时间压力"]
    return ["目标冲突", "环境限制", "关系变化"]


def _genre_atmosphere(genre: str) -> str:
    if "末世" in genre:
        return "紧绷、荒诞、仍有生存意志"
    if "悬疑" in genre:
        return "冷静、压迫、逐步逼近真相"
    if "玄幻" in genre or "修仙" in genre:
        return "开阔、危险、带有规则重量"
    return "贴近人物处境，保持可追踪的现实压力"


def _render_rules(rules: Any) -> str:
    if not isinstance(rules, list) or not rules:
        return "无"
    return "\n".join(
        f"- {item.get('id', '')}：{item.get('rule', '')}。{item.get('description', '')}"
        for item in rules
    )


def _render_locations(locations: Any) -> str:
    if not isinstance(locations, list) or not locations:
        return "无"
    return "\n".join(
        f"- {item.get('id', '')}：{item.get('name', '')}（{item.get('type', '')}，危险等级：{item.get('danger_level', '')}）"
        for item in locations
    )


def _render_mapping(mapping: Any) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "无"
    lines = []
    for key, value in mapping.items():
        rendered = "、".join(str(item) for item in value) if isinstance(value, list) else str(value)
        lines.append(f"- {key}：{rendered}")
    return "\n".join(lines)


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
