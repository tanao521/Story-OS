from __future__ import annotations

from typing import Any


ROLLING_GENERATION_POLICY = {
    "mode": "chapter_by_chapter",
    "plan_next_chapter_only": True,
    "working_context_chapters": 3,
    "older_chapters_strategy": "summarize_and_retrieve",
    "state_update_after_each_chapter": True,
}

PHASE_TITLES = {
    "短篇": ["开端", "转折", "收束"],
    "中篇": ["开局", "发展", "危机", "终局"],
    "长篇": ["开局与规则建立", "关系扩张与初级对抗", "真相逼近与秩序崩坏", "主线爆发与重大反转", "终局重构"],
    "超长篇": ["开局与规则建立", "关系扩张与初级对抗", "真相逼近与秩序崩坏", "主线爆发与重大反转", "终局重构"],
}

GENRE_TENDENCIES = {
    "末世": {
        "focus": ["生存压力", "资源不足", "秩序建立", "外部威胁", "避难所秘密", "人性与荒诞共处"],
        "rules": ["资源分配规则", "避难所运行规则", "外部威胁规律"],
        "locations": ["临时避难所", "废弃城市", "资源封锁区"],
        "truths": ["避难所隐藏旧秩序遗留的秘密"],
    },
    "玄幻": {
        "focus": ["成长体系", "境界或能力规则", "势力冲突", "秘境或传承", "宿命或大道选择"],
        "rules": ["境界成长规则", "传承代价", "势力制衡"],
        "locations": ["边境小城", "宗门或学院", "远古秘境"],
        "truths": ["传承背后存在未付清的代价"],
    },
    "修仙": {
        "focus": ["成长体系", "境界或能力规则", "势力冲突", "秘境或传承", "宿命或大道选择"],
        "rules": ["境界突破规则", "灵气与资源规则", "因果或心魔规则"],
        "locations": ["外门山门", "坊市", "秘境遗址"],
        "truths": ["大道尽头并非单一答案"],
    },
    "都市": {
        "focus": ["现实困境", "身份压力", "关系变化", "事业线或家庭线", "人物成长"],
        "rules": ["职业压力规则", "家庭关系边界", "社会资源流动方式"],
        "locations": ["工作场所", "老城区", "家庭空间"],
        "truths": ["关系变化会暴露身份压力"],
    },
    "悬疑": {
        "focus": ["核心谜团", "线索池", "误导", "阶段性反转", "真相逐步逼近"],
        "rules": ["线索出现规则", "误导与反证规则", "真相揭示节奏"],
        "locations": ["案发现场", "证人活动地", "被隐藏的旧地点"],
        "truths": ["第一层真相只是更深谜团的入口"],
    },
}

GENERAL_TENDENCY = {
    "focus": ["人物目标", "外部阻力", "关系变化", "阶段性危机", "最终选择"],
    "rules": ["核心规则", "代价规则", "冲突升级规则"],
    "locations": ["故事起点", "主要冲突场域", "终局场域"],
    "truths": ["主角目标背后隐藏更大的结构性矛盾"],
}


def generate_blueprint(story_spec: dict[str, Any]) -> dict[str, Any]:
    title = str(story_spec.get("title", "未命名小说"))
    genre = str(story_spec.get("genre", "其他"))
    length_type = str(story_spec.get("length_type", "长篇"))
    target_word_count = int(story_spec.get("target_word_count", 0) or 0)
    tendency = GENRE_TENDENCIES.get(genre, GENERAL_TENDENCY)
    phases = _build_story_phases(length_type, target_word_count, tendency["focus"])

    return {
        "title": title,
        "blueprint_version": "0.2",
        "genre": genre,
        "length_type": length_type,
        "target_word_count": target_word_count,
        "core_premise": _core_premise(story_spec, tendency["focus"]),
        "main_arc": _main_arc(story_spec),
        "core_conflict": _core_conflict(story_spec, tendency["focus"]),
        "ending_direction": _ending_direction(story_spec),
        "world_direction": {
            "world_style": str(story_spec.get("world_style", "")),
            "rules_to_explore": tendency["rules"],
            "important_locations": tendency["locations"],
            "hidden_truths": tendency["truths"],
        },
        "story_phases": phases,
        "chapter_plan": [],
        "initial_foreshadow_pool": _initial_foreshadow_pool(phases),
        "rolling_generation_policy": ROLLING_GENERATION_POLICY.copy(),
    }


def render_blueprint_markdown(blueprint: dict[str, Any]) -> str:
    world = blueprint.get("world_direction", {})
    phases = "\n\n".join(_render_phase(phase) for phase in blueprint.get("story_phases", []))
    foreshadows = _render_foreshadows(blueprint.get("initial_foreshadow_pool", []))

    return f"""# 《{blueprint.get("title", "未命名小说")}》故事蓝图

## 核心设定

- 类型：{blueprint.get("genre", "")}
- 篇幅：{blueprint.get("length_type", "")}
- 预计字数：{blueprint.get("target_word_count", 0)}
- 核心主线：{blueprint.get("main_arc", "")}
- 核心冲突：{blueprint.get("core_conflict", "")}
- 结局方向：{blueprint.get("ending_direction", "")}

## 世界观方向

- 风格：{world.get("world_style", "")}
- 待探索规则：{_join(world.get("rules_to_explore", []))}
- 重要地点：{_join(world.get("important_locations", []))}
- 隐藏真相：{_join(world.get("hidden_truths", []))}

## 故事阶段

{phases}

## 初始伏笔池

{foreshadows}

## 滚动式逐章生成策略

- 每次只规划下一章
- 写完当前章后更新状态
- 只保留最近3章作为工作上下文
- 更早章节压缩为摘要并进入知识库/向量库
- 后续需要时再检索召回
"""


def _build_story_phases(
    length_type: str,
    target_word_count: int,
    conflicts: list[str],
) -> list[dict[str, Any]]:
    titles = PHASE_TITLES.get(length_type, PHASE_TITLES["长篇"])
    phase_count = len(titles)
    return [
        {
            "phase_id": index,
            "title": title,
            "purpose": _phase_purpose(index, phase_count, title),
            "estimated_word_range": _estimated_range(target_word_count, phase_count),
            "main_conflicts": _rotate(conflicts, index, 2),
            "character_changes": _character_changes(index, phase_count),
            "foreshadows_to_plant": [f"fs_{index:03d}"],
            "foreshadows_to_payoff": [] if index == 1 else [f"fs_{index - 1:03d}"],
        }
        for index, title in enumerate(titles, start=1)
    ]


def _initial_foreshadow_pool(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pool = []
    for phase in phases[:3]:
        phase_id = int(phase["phase_id"])
        payoff_phase = min(phase_id + 1, len(phases))
        pool.append(
            {
                "id": f"fs_{phase_id:03d}",
                "content": f"围绕“{phase['title']}”埋设一个可在阶段{payoff_phase}回收的关键信息。",
                "status": "planned",
                "importance": "medium",
                "expected_payoff_phase": payoff_phase,
            }
        )
    return pool


def _core_premise(story_spec: dict[str, Any], focus: list[str]) -> str:
    return (
        f"一部{story_spec.get('genre', '其他')}小说，以{story_spec.get('world_style', '')}"
        f"为世界观方向，在{story_spec.get('tone', '')}的基调中推进{_join(focus[:3])}。"
    )


def _main_arc(story_spec: dict[str, Any]) -> str:
    user_focus = _text_list(story_spec.get("focus", []))
    focus_text = _join(user_focus[:3]) if user_focus else "目标、危机与选择"
    return f"{story_spec.get('character_structure', '主角')}围绕{focus_text}逐步行动，并在局势变化中完成关键选择。"


def _core_conflict(story_spec: dict[str, Any], focus: list[str]) -> str:
    merged = list(dict.fromkeys(_text_list(story_spec.get("focus", [])) + focus))
    return f"人物欲望与{_join(merged[:4])}之间不断升级的冲突。"


def _ending_direction(story_spec: dict[str, Any]) -> str:
    return f"不预设章节细节，以{story_spec.get('tone', '')}基调完成主线选择，并保留可追踪的后续状态。"


def _phase_purpose(index: int, phase_count: int, title: str) -> str:
    if index == 1:
        return f"建立人物处境、核心规则和第一轮行动目标，进入“{title}”。"
    if index == phase_count:
        return f"收束主线矛盾，完成关键选择，并让状态进入可继续追踪的“{title}”。"
    return f"推动矛盾升级，改变人物关系，并为后续阶段埋下“{title}”的压力。"


def _estimated_range(target_word_count: int, phase_count: int) -> str:
    if target_word_count <= 0:
        return "待定"
    average = max(target_word_count // phase_count, 1)
    return f"约 {int(average * 0.8)}~{int(average * 1.2)} 字"


def _rotate(items: list[str], start_index: int, count: int) -> list[str]:
    if not items:
        return []
    offset = start_index - 1
    return [items[(offset + index) % len(items)] for index in range(count)]


def _character_changes(index: int, phase_count: int) -> list[str]:
    if index == 1:
        return ["明确初始欲望", "暴露关键弱点"]
    if index == phase_count:
        return ["完成最终选择", "承担选择后果"]
    return ["关系重新排序", "行动策略升级"]


def _render_phase(phase: dict[str, Any]) -> str:
    return f"""### 阶段{phase.get("phase_id")}：{phase.get("title", "")}

- 作用：{phase.get("purpose", "")}
- 预计字数区间：{phase.get("estimated_word_range", "")}
- 主要冲突：{_join(phase.get("main_conflicts", []))}
- 人物变化：{_join(phase.get("character_changes", []))}
- 埋设伏笔：{_join(phase.get("foreshadows_to_plant", []))}
- 回收伏笔：{_join(phase.get("foreshadows_to_payoff", []))}"""


def _render_foreshadows(foreshadows: Any) -> str:
    if not isinstance(foreshadows, list) or not foreshadows:
        return "无"
    return "\n".join(
        f"- {item.get('id', '')}：{item.get('content', '')}（预计阶段 {item.get('expected_payoff_phase', '')} 回收）"
        for item in foreshadows
    )


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _join(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "、".join(str(item) for item in items)
