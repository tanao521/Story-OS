from __future__ import annotations

import json
import re
from typing import Any

import config
from llm.local_model_service import (
    create_local_model_client,
    generate_draft_with_local_model,
    local_model_draft_warnings,
    should_use_local_model_for_draft,
)


FORBIDDEN_SUMMARY_WORDS = ["显然", "总之", "可以看出"]
INVALID_DRAFT_PHRASES = ["以下是大纲", "作为AI", "作为 AI", "我无法"]


def write_chapter_draft(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    chapter_plan: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = build_draft_prompt(
        story_spec,
        blueprint,
        characters,
        world_bible,
        state,
        chapter_plan,
        working_context,
    )
    mock_text = _build_draft_text(story_spec, world_bible, chapter_plan)
    draft_text = mock_text
    generation = _mock_generation(fallback_used=False, warnings=[])

    if should_use_local_model_for_draft():
        local_text, warnings = generate_draft_with_local_model(prompt, create_local_model_client())
        invalid_reason = _invalid_draft_reason(local_text)
        if invalid_reason is None:
            draft_text = local_text
            generation = {
                "mode": "local_model",
                "model": config.LOCAL_MODEL_NAME,
                "fallback_used": False,
                "warnings": warnings,
            }
        else:
            warnings.append(f"本地模型输出无效，已回退 mock：{invalid_reason}")
            generation = _mock_generation(fallback_used=True, warnings=warnings)
    else:
        warnings = local_model_draft_warnings()
        if warnings:
            generation = _mock_generation(fallback_used=True, warnings=warnings)

    draft_text = clean_ai_style(draft_text)
    actual_word_count = _count_chinese_like_chars(draft_text)
    self_check = self_check_draft(draft_text, chapter_plan)
    if working_context is None:
        self_check.setdefault("warnings", []).append("未使用 current_context.json，建议先运行 python main.py build-context。")

    return {
        "draft_version": "1.1",
        "chapter_id": int(chapter_plan.get("chapter_id", 1)),
        "chapter_title": str(chapter_plan.get("chapter_title", "")),
        "status": "draft",
        "estimated_word_count": int(chapter_plan.get("estimated_word_count", 3000) or 3000),
        "actual_word_count": actual_word_count,
        "based_on_plan_path": "data/next_chapter_plan.json",
        "draft_text": draft_text,
        "generation": generation,
        "memory_context_used": _memory_context_used(working_context),
        "used_context": {
            "story_spec_summary": _story_spec_summary(story_spec),
            "characters_used": chapter_plan.get("required_context", {}).get("characters_to_use", []),
            "world_rules_used": chapter_plan.get("required_context", {}).get("world_rules_to_use", []),
            "continuity_constraints_used": chapter_plan.get("continuity_constraints", []),
        },
        "self_check": self_check,
    }


def build_draft_prompt(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    chapter_plan: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> str:
    payload = {
        "story_spec_summary": _story_spec_summary(story_spec),
        "blueprint_summary": _blueprint_summary(blueprint),
        "chapter_plan": chapter_plan,
        "characters_for_this_chapter": _characters_for_chapter(characters, chapter_plan),
        "world_rules_for_this_chapter": _world_rules_for_chapter(world_bible, chapter_plan),
        "state_snapshot": _state_snapshot(state),
        "working_context": _working_context_summary(working_context),
    }
    return (
        "你是中文小说正文写作 Agent。\n"
        "你的任务是只写当前这一章草稿。\n\n"
        "强制边界：\n"
        "只写当前章正文，不写下一章，不写大纲，不写作者说明。\n"
        "不要输出 JSON。\n"
        "不要输出分析。\n"
        "不要输出标题以外的元信息。\n"
        "你不能提前写后续章节。\n"
        "你不能改变已经确定的世界观规则。\n"
        "你不能让人物知道自己没有经历过的信息。\n\n"
        "避免明显 AI 味：\n"
        "- 少用“不是A，而是B”\n"
        "- 少用破折号\n"
        "- 避免“显然”“总之”“可以看出”\n"
        "- 避免过度解释情绪\n"
        "- 用动作、环境和细节表达人物状态\n\n"
        "输出要求：\n"
        "直接输出小说正文。\n"
        "不要输出 JSON。\n"
        "不要输出说明。\n"
        "正文长度控制在 1200~1800 中文字左右。\n\n"
        "输入资料：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def is_valid_draft_text(text: str, min_chars: int = 500) -> bool:
    return _invalid_draft_reason(text, min_chars=min_chars) is None


def render_draft_markdown(draft: dict[str, Any]) -> str:
    warnings = draft.get("self_check", {}).get("warnings", [])
    generation = draft.get("generation", {})
    generation_warnings = generation.get("warnings", [])
    return f"""# 第{draft.get("chapter_id", "")}章 {draft.get("chapter_title", "")}（草稿）

## 状态

- 版本：{draft.get("draft_version", "1.1")}
- 状态：{draft.get("status", "")}
- 预计字数：{draft.get("estimated_word_count", 0)}
- 实际字数：{draft.get("actual_word_count", 0)}
- 基于计划：{draft.get("based_on_plan_path", "")}
- 生成模式：{generation.get("mode", "mock")}
- 模型：{generation.get("model", "mock")}
- 是否 fallback：{generation.get("fallback_used", False)}

## 正文

{draft.get("draft_text", "")}

## 自检

- 是否包含必要事件：{draft.get("self_check", {}).get("included_required_events", False)}
- 是否包含结尾钩子：{draft.get("self_check", {}).get("included_ending_hook", False)}
- 是否遵守人物声音：{draft.get("self_check", {}).get("followed_voice_requirements", False)}
- 是否遵守文风要求：{draft.get("self_check", {}).get("followed_style_requirements", False)}

## 生成警告

{_render_list(generation_warnings) if generation_warnings else "无"}

## 自检警告

{_render_list(warnings) if warnings else "无"}
"""


def clean_ai_style(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"不是([^，。；\n]{1,24})，?而是", r"\1转为", cleaned)
    cleaned = re.sub(r"[-—]{2,}", "，", cleaned)
    for word in FORBIDDEN_SUMMARY_WORDS:
        cleaned = cleaned.replace(word, "")
    return cleaned


def self_check_draft(draft_text: str, chapter_plan: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    ending_hook = str(chapter_plan.get("pacing_design", {}).get("ending_hook", ""))
    included_ending_hook = _contains_hook(draft_text, ending_hook)
    included_required_events = _contains_must_include(draft_text, chapter_plan)

    dash_count = draft_text.count("—") + draft_text.count("--")
    not_but_count = min(draft_text.count("不是"), draft_text.count("而是"))
    if dash_count > 3:
        warnings.append("破折号数量超过 3 个")
    if not_but_count > 2:
        warnings.append("“不是，而是”句式出现过多")
    if _count_chinese_like_chars(draft_text) < 500:
        warnings.append("正文长度过短")
    if not included_ending_hook:
        warnings.append("未检测到结尾钩子")
    if not included_required_events:
        warnings.append("未检测到必要事件")

    return {
        "included_required_events": included_required_events,
        "included_ending_hook": included_ending_hook,
        "followed_voice_requirements": dash_count <= 3,
        "followed_style_requirements": not_but_count <= 2 and all(word not in draft_text for word in FORBIDDEN_SUMMARY_WORDS),
        "warnings": warnings,
    }


def _invalid_draft_reason(text: str, min_chars: int = 500) -> str | None:
    stripped = text.strip()
    if not stripped:
        return "空文本"
    if _looks_like_json(stripped):
        return "看起来像 JSON"
    for phrase in INVALID_DRAFT_PHRASES:
        if phrase in stripped:
            return f"包含禁止短语：{phrase}"
    if stripped.startswith(("分析：", "说明：", "大纲：", "以下是分析", "以下是说明")):
        return "只输出了分析或说明"
    if _count_chinese_like_chars(stripped) < min_chars:
        return f"正文少于 {min_chars} 字"
    return None


def _looks_like_json(text: str) -> bool:
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _build_draft_text(
    story_spec: dict[str, Any],
    world_bible: dict[str, Any],
    chapter_plan: dict[str, Any],
) -> str:
    genre = str(story_spec.get("genre", ""))
    chapter_goal = str(chapter_plan.get("chapter_goal", ""))
    main_conflict = str(chapter_plan.get("conflict_design", {}).get("main_conflict", ""))
    ending_hook = str(chapter_plan.get("pacing_design", {}).get("ending_hook", ""))
    scenes = chapter_plan.get("scene_plan", [])
    voice_profiles = chapter_plan.get("voice_requirements", {}).get("character_voice_profiles", {})
    character_names = _character_names(chapter_plan)
    first_character = character_names[0] if character_names else "他"

    paragraphs = [
        _opening_paragraph(genre, first_character, chapter_goal, main_conflict),
        _world_rule_paragraph(world_bible, chapter_plan),
    ]
    if isinstance(scenes, list):
        for scene in scenes:
            if isinstance(scene, dict):
                paragraphs.extend(_scene_paragraphs(scene, genre, first_character, voice_profiles))
    paragraphs.extend([
        _continuity_paragraph(chapter_plan),
        _ending_hook_paragraph(first_character, ending_hook),
    ])
    draft_text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())
    return _pad_to_demo_length(draft_text, genre, first_character, chapter_plan)


def _opening_paragraph(genre: str, first_character: str, chapter_goal: str, main_conflict: str) -> str:
    texture = _genre_texture(genre)
    return (
        f"{texture}。{first_character}在原地停了几秒，先听见自己的呼吸，又听见更远处传来的细碎声响。"
        f"这一章的目标压在他眼前：{chapter_goal}。{main_conflict}没有给他留下太多整理思路的时间。"
    )


def _world_rule_paragraph(world_bible: dict[str, Any], chapter_plan: dict[str, Any]) -> str:
    rules = chapter_plan.get("required_context", {}).get("world_rules_to_use", [])
    if not rules:
        rules = world_bible.get("core_rules", [])
    rule_text = _rule_text(rules)
    return (
        f"他没有立刻行动。这个世界的规则已经摆在那里：{rule_text}。"
        "任何轻率的选择都会留下痕迹，物资、时间、伤势和关系变化都不会凭空消失。"
    )


def _scene_paragraphs(scene: dict[str, Any], genre: str, first_character: str, voice_profiles: Any) -> list[str]:
    scene_title = str(scene.get("scene_title", ""))
    location = str(scene.get("location", "待定地点"))
    conflict = str(scene.get("conflict", ""))
    must_include = _usable_must_include(scene.get("must_include", []))
    emotional_beat = str(scene.get("emotional_beat", ""))
    dialogue = _dialogue_line(first_character, voice_profiles)
    return [
        (
            f"{scene_title}发生在{location}。{_genre_detail(genre)}"
            f"{first_character}把能确认的东西一件件放进心里：门、光、声音，还有身边人的位置。"
        ),
        (
            f"压力很快变得具体。{conflict}贴着场景推进，{must_include}。"
            "他没有把情绪说出口，只把手指收紧，逼自己先判断哪一步最容易出错。"
        ),
        (
            f"“{dialogue}。”{first_character}说。话说得不长，{emotional_beat}却在短暂停顿里浮出来。"
            "旁人若在场，只会看到他换了一个站位，看不到他已经把退路和代价都算了一遍。"
        ),
    ]


def _continuity_paragraph(chapter_plan: dict[str, Any]) -> str:
    constraints = chapter_plan.get("continuity_constraints", [])
    constraint_text = "；".join(str(item) for item in constraints[:3]) if isinstance(constraints, list) else ""
    return (
        f"他提醒自己，{constraint_text}。"
        "这些限制让每个动作都变慢，也让每次沉默都有了重量。眼下能做的不是解释一切，而是先活过这一次判断。"
    )


def _ending_hook_paragraph(first_character: str, ending_hook: str) -> str:
    return (
        f"最后的变化来得很轻。{first_character}听见某处响了一下，像金属在冷墙里慢慢收紧。"
        f"{ending_hook}他抬头时，才发现自己刚才以为安全的方向，正留下第二道更深的痕迹。"
    )


def _pad_to_demo_length(draft_text: str, genre: str, first_character: str, chapter_plan: dict[str, Any]) -> str:
    target = 900 if int(chapter_plan.get("estimated_word_count", 3000) or 3000) <= 1500 else 1300
    additions = []
    while _count_chinese_like_chars(draft_text + "\n\n".join(additions)) < target:
        additions.append(
            f"{first_character}又检查了一遍周围。{_genre_detail(genre)}"
            "他没有急着给自己找理由，只把看到的变化记下来：可用的东西少了一点，未知的声音近了一点，"
            "身边人的反应也慢慢露出差别。每一处差别都可能变成下一次选择的代价。"
        )
    return "\n\n".join([draft_text, *additions])


def _mock_generation(fallback_used: bool, warnings: list[str]) -> dict[str, Any]:
    return {
        "mode": "mock",
        "model": "mock",
        "fallback_used": fallback_used,
        "warnings": warnings,
    }


def _story_spec_summary(story_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": story_spec.get("title", ""),
        "genre": story_spec.get("genre", ""),
        "length_type": story_spec.get("length_type", ""),
        "tone": story_spec.get("tone", ""),
        "writing_style": story_spec.get("writing_style", ""),
        "narration": story_spec.get("narration", ""),
        "avoid": story_spec.get("avoid", []),
        "anti_ai_style_rules": story_spec.get("anti_ai_style_rules", []),
    }


def _blueprint_summary(blueprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "core_premise": blueprint.get("core_premise", ""),
        "main_arc": blueprint.get("main_arc", ""),
        "core_conflict": blueprint.get("core_conflict", ""),
        "ending_direction": blueprint.get("ending_direction", ""),
        "current_story_phases": blueprint.get("story_phases", [])[:5],
    }


def _characters_for_chapter(characters: dict[str, Any], chapter_plan: dict[str, Any]) -> list[dict[str, Any]]:
    planned = chapter_plan.get("required_context", {}).get("characters_to_use", [])
    if not isinstance(planned, list):
        return []
    wanted_ids = {item.get("id") for item in planned if isinstance(item, dict)}
    wanted_names = {item.get("name") for item in planned if isinstance(item, dict)}
    all_characters = characters.get("main_characters", []) + characters.get("supporting_characters", [])
    result = [
        item
        for item in all_characters
        if isinstance(item, dict) and (item.get("id") in wanted_ids or item.get("name") in wanted_names)
    ]
    return result or [item for item in planned if isinstance(item, dict)]


def _world_rules_for_chapter(world_bible: dict[str, Any], chapter_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "rules_to_use": chapter_plan.get("required_context", {}).get("world_rules_to_use", []),
        "continuity_constraints": chapter_plan.get("continuity_constraints", []),
        "world_style": world_bible.get("world_style", ""),
    }


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    foreshadows = state.get("foreshadows", [])
    return {
        "current_chapter": state.get("current_chapter", 0),
        "current_stage": state.get("current_stage", ""),
        "characters": state.get("characters", {}),
        "world": state.get("world", {}),
        "plot": state.get("plot", {}),
        "open_foreshadows": [
            item
            for item in foreshadows
            if isinstance(item, dict) and item.get("status") in {"open", "planned"}
        ] if isinstance(foreshadows, list) else [],
    }


def _working_context_summary(working_context: dict[str, Any] | None) -> dict[str, Any]:
    if working_context is None:
        return {
            "recent_chapters": [],
            "retrieved_summaries": [],
            "vector_retrieved_memories": [],
        }
    return {
        "mode": working_context.get("mode", ""),
        "recent_chapters": [_compact_context_item(item) for item in working_context.get("recent_chapters", [])[:3]],
        "retrieved_summaries": [_compact_context_item(item) for item in working_context.get("retrieved_summaries", [])[:5]],
        "vector_retrieved_memories": [
            _compact_context_item(item)
            for item in working_context.get("vector_retrieved_memories", [])[:5]
        ],
    }


def _compact_context_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    compact: dict[str, Any] = {}
    for key in ["chapter_id", "title", "chapter_title", "short_summary", "summary", "text", "content"]:
        if key in item:
            value = item[key]
            compact[key] = value[:800] if isinstance(value, str) else value
    return compact


def _contains_hook(draft_text: str, ending_hook: str) -> bool:
    if not ending_hook:
        return True
    keywords = [part for part in re.split(r"[：，。；、\s]+", ending_hook) if len(part) >= 2]
    return any(keyword in draft_text for keyword in keywords[:4])


def _contains_must_include(draft_text: str, chapter_plan: dict[str, Any]) -> bool:
    scenes = chapter_plan.get("scene_plan", [])
    if not isinstance(scenes, list):
        return False
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        for item in scene.get("must_include", []):
            text = str(item)
            if text and "不要写成正文" not in text and text in draft_text:
                return True
    return False


def _character_names(chapter_plan: dict[str, Any]) -> list[str]:
    characters = chapter_plan.get("required_context", {}).get("characters_to_use", [])
    if not isinstance(characters, list):
        return []
    return [str(character.get("name", "")) for character in characters if isinstance(character, dict) and character.get("name")]


def _dialogue_line(first_character: str, voice_profiles: Any) -> str:
    if isinstance(voice_profiles, dict) and first_character in voice_profiles:
        tone = voice_profiles[first_character].get("tone", "克制")
        if tone in {"直接", "带刺"}:
            return "别急，先看清楚哪一样东西少了"
    return "先别出声，听"


def _usable_must_include(items: Any) -> str:
    if not isinstance(items, list):
        return "关键细节必须落到行动里"
    for item in items:
        text = str(item)
        if text and "不要写成正文" not in text:
            return text
    return "关键细节必须落到行动里"


def _rule_text(rules: Any) -> str:
    if not isinstance(rules, list) or not rules:
        return "写作时必须遵守已建立世界观规则"
    names = []
    for rule in rules[:3]:
        if isinstance(rule, dict):
            names.append(str(rule.get("rule", "")))
        else:
            names.append(str(rule))
    return "、".join(name for name in names if name)


def _genre_texture(genre: str) -> str:
    if "末世" in genre:
        return "冷光贴着水泥墙滑下去，灰尘在地下室的空气里缓慢翻动"
    if "玄幻" in genre or "修仙" in genre:
        return "细薄的灵气贴着经脉游走，像一条不肯完全听命的冷线"
    if "都市" in genre:
        return "手机屏幕暗下去，楼道里的灯迟了一拍才亮"
    if "悬疑" in genre:
        return "房间里有一处细节和记忆对不上，安静得过分"
    return "天色压低，周围的声音变得清楚"


def _genre_detail(genre: str) -> str:
    if "末世" in genre:
        return "冷光、灰尘、水泥墙和远处的金属声把空间压得很低。通讯图标仍是灰的，物资袋轻得让人心里发空。"
    if "玄幻" in genre or "修仙" in genre:
        return "灵气在皮肤下缓慢回落，能力的边界清清楚楚，任何强行突破都要付出代价。"
    if "都市" in genre:
        return "电梯数字一格格跳动，未读消息压在屏幕上，现实压力没有给人留出体面退路。"
    if "悬疑" in genre:
        return "那枚异常细节安静地待在原处，像一条不肯闭合的线索。"
    return "环境没有给出答案，只把选择推到眼前。"


def _count_chinese_like_chars(text: str) -> int:
    return len([char for char in text if not char.isspace()])


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _memory_context_used(working_context: dict[str, Any] | None) -> dict[str, Any]:
    if working_context is None:
        return {
            "recent_chapters_count": 0,
            "retrieved_summaries_count": 0,
            "mode": "none",
        }
    budget = working_context.get("memory_budget", {})
    return {
        "recent_chapters_count": budget.get("recent_chapters_count", 0),
        "retrieved_summaries_count": budget.get("retrieved_summaries_count", 0),
        "mode": working_context.get("mode", "sliding_window_plus_summary_retrieval"),
    }
