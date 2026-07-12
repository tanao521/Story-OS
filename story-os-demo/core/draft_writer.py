from __future__ import annotations

import json
import re
from typing import Any

import config
from core.llm_api_model import (
    generate_with_api_model,
    load_api_model_settings,
    should_use_api_model_for_draft,
)


FORBIDDEN_SUMMARY_WORDS = ["显然", "总之", "可以看出"]
INVALID_DRAFT_PHRASES = ["以下是大纲", "作为AI", "作为 AI", "我无法"]
CHAPTER_WORD_OVERFLOW_TOLERANCE = 1500


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
    min_chars, max_chars = _chapter_word_bounds(story_spec, chapter_plan)
    mock_text = _build_draft_text(story_spec, world_bible, chapter_plan)
    draft_text = mock_text
    generation = _mock_generation(
        fallback_used=True,
        warnings=["\u672c\u5730\u6a21\u578b\u672a\u542f\u7528\uff0c\u5df2\u4f7f\u7528 mock \u793a\u4f8b\u6587\u672c\u3002"],
    )

    if should_use_api_model_for_draft():
        cloud_text, warnings = _generate_api_model_draft(prompt, min_chars)
        cloud_text = clean_ai_style(cloud_text)
        if not cloud_text.strip():
            if not warnings:
                warnings = ["API ??? 云端模型没有返回正文。"]
            generation = _mock_generation(fallback_used=True, warnings=warnings)
        else:
            invalid_reason = _invalid_draft_reason(cloud_text, min_chars=min_chars)
            constraint_violations = _draft_constraint_violations(cloud_text, story_spec, chapter_plan)
            if invalid_reason is None and not constraint_violations:
                draft_text = cloud_text
                settings = load_api_model_settings()
                generation = {
                    "mode": "api_model",
                    "model": settings["model"],
                    "fallback_used": False,
                    "warnings": warnings,
                }
            else:
                first_reasons = _merge_reasons(invalid_reason, constraint_violations)
                repair_prompt = _build_constraint_repair_prompt(
                    prompt,
                    cloud_text,
                    first_reasons,
                    story_spec,
                    chapter_plan,
                    min_chars,
                    max_chars,
                )
                repaired_text, repair_warnings = _generate_api_model_draft(repair_prompt, max_chars)
                warnings.extend(repair_warnings)
                repaired_text = clean_ai_style(repaired_text)
                if not repaired_text.strip():
                    final_reasons = _merge_reasons("API ??? 云端模型重写后仍未返回正文", []) or first_reasons
                    warnings.append(
                        "API ??? 云端模型生成失败，已回退 mock："
                        + "；".join(final_reasons[:4])
                    )
                    generation = _mock_generation(fallback_used=True, warnings=warnings)
                else:
                    repair_invalid_reason = _invalid_draft_reason(repaired_text, min_chars=min_chars)
                    repair_violations = _draft_constraint_violations(repaired_text, story_spec, chapter_plan)
                    if repair_invalid_reason is None and not repair_violations:
                        draft_text = repaired_text
                        settings = load_api_model_settings()
                        warnings.append("初稿未通过写作约束，已调用 API ??? 云端模型重写。")
                        generation = {
                            "mode": "api_model",
                            "model": settings["model"],
                            "fallback_used": False,
                            "warnings": warnings,
                            "constraint_repair_used": True,
                            "rejected_cloud_reasons": first_reasons,
                        }
                    else:
                        final_reasons = _merge_reasons(repair_invalid_reason, repair_violations) or first_reasons
                        warnings.append(
                            "API ??? 云端模型生成失败，已回退 mock："
                            + "；".join(final_reasons[:4])
                        )
                        generation = _mock_generation(fallback_used=True, warnings=warnings)
    else:
        warnings = ["LLM_PROVIDER 未配置为 api_model，已使用 mock 示例文本。"]
        generation = _mock_generation(fallback_used=True, warnings=warnings)

    draft_text = clean_ai_style(draft_text)
    actual_word_count = _count_chinese_like_chars(draft_text)
    self_check = self_check_draft(draft_text, chapter_plan)
    if working_context is None:
        self_check.setdefault("warnings", []).append("未使用 current_context.json，建议先运行 python main.py build-context。")

    # Extract the real title from the generated text (e.g. "# 第2章 还原后的空白")
    actual_title = _extract_title_from_text(draft_text) or str(chapter_plan.get("chapter_title", ""))
    return {
        "draft_version": "1.1",
        "chapter_id": int(chapter_plan.get("chapter_id", 1)),
        "chapter_title": actual_title,
        "status": "draft",
        "estimated_word_count": int(chapter_plan.get("estimated_word_count", 3000) or 3000),
        "actual_word_count": actual_word_count,
        "based_on_plan_path": "data/next_chapter_plan.json",
        "draft_text": draft_text,
        "generation": generation,
        "memory_context_used": _memory_context_used(working_context),
        "used_context": {
            "story_spec_summary": _story_spec_summary(story_spec),
            "writing_constraints": _writing_constraints_summary(story_spec),
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
    min_chars, max_chars = _chapter_word_bounds(story_spec, chapter_plan)
    payload = {
        "story_spec_summary": _story_spec_summary(story_spec),
        "writing_constraints": _writing_constraints_summary(story_spec),
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
        "第一行必须是章节标题，格式：# 第X章 标题名\n"
        "标题名根据本章核心情节自拟，4-8个汉字。\n"
        "不要输出 JSON。\n"
        "不要输出说明。\n"
        "\u5fc5\u987b\u4f7f\u7528\u4e2d\u6587\uff0c\u4e0d\u8981\u7528\u82f1\u6587\u5199\u6b63\u6587\u3002\n"
        f"\u6b63\u6587\u957f\u5ea6\u4f18\u5148\u63a7\u5236\u5728 {min_chars}~{max_chars} \u4e2a\u975e\u7a7a\u767d\u5b57\u7b26\u5185\uff1b\u5982\u679c\u7565\u8d85\u4e0a\u9650\uff0c\u6700\u591a\u5141\u8bb8\u8d85\u51fa {CHAPTER_WORD_OVERFLOW_TOLERANCE} \u4e2a\u5b57\u7b26\uff0c\u4f46\u4e0d\u8981\u660e\u663e\u8d85\u5f97\u592a\u591a\u3002\n"
        f"\u5982\u679c\u7565\u8d85\u4e0a\u9650\uff0c\u6700\u591a\u5bb9\u8bb8\u8d85\u51fa CHAPTER_WORD_OVERFLOW_TOLERANCE \u4e2a\u5b57\u7b26\uff0c\u4f46\u4e0d\u8981\u660e\u663e\u8d85\u5f97\u592a\u591a\u3002\n"
        "\u5fc5\u987b\u9075\u5b88\u8f93\u5165\u8d44\u6599\u4e2d writing_constraints \u7684 must_follow / must_avoid / ai_style_limits\u3002\n\n"
        "输入资料：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _constraint_prompt_block(story_spec: dict[str, Any], min_chars: int, max_chars: int) -> str:
    constraints = _writing_constraints_summary(story_spec)
    must_follow = _constraint_items(constraints.get("must_follow"))
    must_avoid = _constraint_items(constraints.get("must_avoid"))
    ai_limits = _constraint_items(constraints.get("ai_style_limits"))
    pacing = str(constraints.get("pacing", "") or "").strip()
    structure = str(constraints.get("chapter_structure", "") or "").strip()
    lines = [
        "最高优先级写作约束（用于引导生成，不要求在正文中原样出现）：",
        "- 下面这些是写作规则与设定要求，模型需要遵守，不要直接把它们当成正文内容输出。",
        f"- 正文长度必须在 {min_chars}~{max_chars} 个非空白字符内；少于 {min_chars} 或多于 {max_chars} 都视为失败。",
    ]
    if pacing:
        lines.append(f"- ?????{pacing}")
    if structure:
        lines.append(f"- ?????{structure}")
    if must_follow:
        lines.append("- 写作/设定指令")
        lines.extend(f"  - {item}" for item in must_follow[:20])
    if must_avoid:
        lines.append("- ?????")
        lines.extend(f"  - {item}" for item in must_avoid[:20])
    if ai_limits:
        lines.append("- AI ????")
        lines.extend(f"  - {item}" for item in ai_limits[:20])
    lines.append("- ??????????????????????????????????????")
    return "\n".join(lines)


def is_valid_draft_text(text: str, min_chars: int = 500) -> bool:
    return _invalid_draft_reason(text, min_chars=min_chars) is None


def _generate_api_model_draft(prompt: str, target_chars: int) -> tuple[str, list[str]]:
    try:
        text = generate_with_api_model([
            {
                "role": "system",
                "content": f"?? Story OS ????????????????????????? writing_constraints ?? must_follow / must_avoid / ai_style_limits?????????????????????????????????????????? {target_chars} ???????",
            },
            {"role": "user", "content": prompt},
        ])
        return text, []
    except Exception as exc:
        return "", [f"API ??? ?????????{exc}"]
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
    min_chars, _ = _chapter_word_bounds({}, chapter_plan)
    if _count_chinese_like_chars(draft_text) < min_chars:
        warnings.append(f"\u6b63\u6587\u957f\u5ea6\u4f4e\u4e8e\u7ea6\u675f\u4e0b\u9650 {min_chars}")
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


def _draft_constraint_violations(
    text: str,
    story_spec: dict[str, Any],
    chapter_plan: dict[str, Any],
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    min_chars, max_chars = _chapter_word_bounds(story_spec, chapter_plan)
    actual_chars = _count_chinese_like_chars(stripped)
    violations: list[str] = []
    if actual_chars < min_chars:
        violations.append(f"\u6b63\u6587\u5c11\u4e8e\u7ea6\u675f\u4e0b\u9650 {min_chars}\uff0c\u5f53\u524d {actual_chars}")
    soft_max_chars = max_chars + CHAPTER_WORD_OVERFLOW_TOLERANCE
    if actual_chars > soft_max_chars:
        violations.append(
            f"\u6b63\u6587\u8d85\u8fc7\u7ea6\u675f\u4e0a\u9650 {max_chars}\uff0c"
            f"\u5f53\u524d {actual_chars}\uff0c\u5bb9\u8bb8\u6700\u5927\u504f\u5dee {CHAPTER_WORD_OVERFLOW_TOLERANCE}"
        )
    if _cjk_ratio(stripped) < 0.55:
        violations.append("\u4e2d\u6587\u5360\u6bd4\u8fc7\u4f4e\uff0c\u7591\u4f3c\u82f1\u6587\u6216\u975e\u4e2d\u6587\u6b63\u6587")

    constraints = _writing_constraints_summary(story_spec)
    avoid_items = [
        *_constraint_items(story_spec.get("avoid")),
        *_constraint_items(constraints.get("must_avoid")),
        *_constraint_items(constraints.get("ai_style_limits")),
    ]
    for item in _unique_items(avoid_items):
        if item and item in stripped:
            violations.append(f"\u5305\u542b\u7528\u6237\u7981\u7528\u5185\u5bb9\uff1a{item[:40]}")

    return violations


def _build_constraint_repair_prompt(
    original_prompt: str,
    rejected_text: str,
    violations: list[str],
    story_spec: dict[str, Any],
    chapter_plan: dict[str, Any],
    min_chars: int,
    max_chars: int,
) -> str:
    constraints = _writing_constraints_summary(story_spec)
    rejected_excerpt = rejected_text[:1600]
    return (
        "\u4e0a\u4e00\u6b21\u672c\u5730\u6a21\u578b\u751f\u6210\u7684\u8349\u7a3f\u672a\u901a\u8fc7\u9a8c\u6536\uff0c\u4e0d\u5141\u8bb8\u76f4\u63a5\u4fee\u8865\u6216\u7eed\u5199\u3002\n"
        "\u8bf7\u5b8c\u5168\u91cd\u5199\u5f53\u524d\u7ae0\u7684\u4e2d\u6587\u5c0f\u8bf4\u6b63\u6587\uff0c\u53ea\u8f93\u51fa\u6b63\u6587\u3002\n\n"
        "\u9a8c\u6536\u5931\u8d25\u539f\u56e0\uff1a\n"
        f"{json.dumps(violations, ensure_ascii=False, indent=2)}\n\n"
        "\u672c\u6b21\u5fc5\u987b\u540c\u65f6\u6ee1\u8db3\uff1a\n"
        "- \u5168\u6587\u4f7f\u7528\u4e2d\u6587\u53d9\u4e8b\uff0c\u4e0d\u8981\u5199\u82f1\u6587\u6b63\u6587\u3002\n"
        f"- \u6b63\u6587\u957f\u5ea6\u4f18\u5148\u63a7\u5236\u5728 {min_chars}~{max_chars} \u4e2a\u975e\u7a7a\u767d\u5b57\u7b26\u5185\uff0c\u5982\u679c\u8d85\u51fa\u4e0a\u9650\uff0c\u6700\u591a\u5141\u8bb8\u8d85\u51fa {CHAPTER_WORD_OVERFLOW_TOLERANCE} \u4e2a\u5b57\u7b26\uff0c\u4f46\u4e0d\u8981\u660e\u663e\u8d85\u5f97\u592a\u591a\u3002\n"
        "- \u5fc5\u987b\u9075\u5b88\u7528\u6237\u5728 Web \u7ea6\u675f\u9762\u677f\u4e2d\u63d0\u4ea4\u7684\u8865\u5145\u7ea6\u675f\u3002\n"
        "- \u4e0d\u8981\u8f93\u51fa JSON\u3001\u5206\u6790\u3001\u63d0\u7eb2\u3001\u89e3\u91ca\u6216\u4f5c\u8005\u8bf4\u660e\u3002\n\n"
        "Web \u7ea6\u675f\uff1a\n"
        f"{json.dumps(constraints, ensure_ascii=False, indent=2)}\n\n"
        "\u88ab\u62d2\u7edd\u7684\u7247\u6bb5\uff08\u4ec5\u7528\u4e8e\u907f\u514d\u91cd\u590d\u9519\u8bef\uff09\uff1a\n"
        f"{rejected_excerpt}\n\n"
        "\u539f\u59cb\u5199\u4f5c\u8f93\u5165\uff1a\n"
        f"{original_prompt}"
    )


def _merge_reasons(reason: str | None, violations: list[str]) -> list[str]:
    reasons = []
    if reason:
        reasons.append(reason)
    reasons.extend(violations)
    return reasons


def _constraint_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value).replace("\uff1b", "\n").replace(";", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.splitlines() if item.strip()]


def _required_terms_from_must_follow(value: Any) -> list[str]:
    terms: list[str] = []
    for item in _constraint_items(value):
        normalized = item.strip()
        if not normalized:
            continue
        terms.extend(
            match.group(0).strip()
            for match in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:[ -][A-Za-z0-9]+){0,6}", normalized)
        )
        chunks = [chunk.strip() for chunk in re.split(r"[???;?,/\n\t\s]+", normalized) if chunk.strip()]
        if not chunks:
            chunks = [normalized]
        for chunk in chunks:
            if 2 <= len(chunk) <= 40:
                if any(_is_cjk(char) for char in chunk) or re.search(r"[A-Za-z]", chunk):
                    terms.append(chunk)
        if 2 <= len(normalized) <= 40:
            terms.append(normalized)
    return _unique_items(terms)


def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _cjk_ratio(text: str) -> float:
    total = _count_chinese_like_chars(text)
    if total <= 0:
        return 0.0
    cjk = sum(1 for char in text if _is_cjk(char))
    return cjk / total


def _is_cjk(char: str) -> bool:
    return (
        "\u4e00" <= char <= "\u9fff"
        or "\u3400" <= char <= "\u4dbf"
        or "\u3000" <= char <= "\u303f"
        or "\uff00" <= char <= "\uffef"
    )


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
    return _pad_to_demo_length(draft_text, genre, first_character, story_spec, chapter_plan)


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


def _pad_to_demo_length(
    draft_text: str,
    genre: str,
    first_character: str,
    story_spec: dict[str, Any],
    chapter_plan: dict[str, Any],
) -> str:
    target, _ = _chapter_word_bounds(story_spec, chapter_plan)
    additions = []
    while _count_chinese_like_chars(draft_text + "\n\n".join(additions)) < target:
        additions.append(
            f"{first_character}又检查了一遍周围。{_genre_detail(genre)}"
            "他没有急着给自己找理由，只把看到的变化记下来：可用的东西少了一点，未知的声音近了一点，"
            "身边人的反应也慢慢露出差别。每一处差别都可能变成下一次选择的代价。"
        )
    return "\n\n".join([draft_text, *additions])


def _chapter_word_bounds(story_spec: dict[str, Any], chapter_plan: dict[str, Any]) -> tuple[int, int]:
    constraints = story_spec.get("writing_constraints", {}) if isinstance(story_spec, dict) else {}
    if not isinstance(constraints, dict):
        constraints = {}
    chapter = constraints.get("chapter_word_count", {})
    if not isinstance(chapter, dict):
        chapter = {}
    plan_limits = chapter_plan.get("word_count_constraints", {}) if isinstance(chapter_plan, dict) else {}
    if not isinstance(plan_limits, dict):
        plan_limits = {}
    minimum = _positive_int(chapter.get("min"), 0) or _positive_int(plan_limits.get("min"), 0)
    maximum = _positive_int(chapter.get("max"), 0) or _positive_int(plan_limits.get("max"), 0)
    if minimum <= 0:
        minimum = 1200
    if maximum <= 0:
        maximum = max(minimum, 1800)
    if maximum < minimum:
        maximum = minimum
    return minimum, maximum


def _writing_constraints_summary(story_spec: dict[str, Any]) -> dict[str, Any]:
    constraints = story_spec.get("writing_constraints", {}) if isinstance(story_spec, dict) else {}
    return constraints if isinstance(constraints, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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
    """Extract the 3-tier memory from the working context for the LLM prompt.

    Layer 1 (global_memory)   — always included, compact
    Layer 2 (recent_memory)   — 1 full prev chapter + 3 summaries
    Layer 3 (retrieval_memory)— vector + keyword results, only when relevant
    """
    if working_context is None:
        return {
            "global_memory": {},
            "recent_memory": {},
            "retrieval_memory": {},
        }

    recent = working_context.get("recent_memory", {})
    retrieval = working_context.get("retrieval_memory", {})

    prev_full = recent.get("previous_chapter_full")
    return {
        "global_memory": working_context.get("global_memory", {}),
        "recent_memory": {
            "previous_chapter_full": _compact_prev_chapter(prev_full) if prev_full else None,
            "recent_summaries": [
                _compact_context_item(s) for s in recent.get("recent_summaries", [])[:3]
            ],
        },
        "retrieval_memory": {
            "vector_results": [
                _compact_context_item(r)
                for r in retrieval.get("vector_results", [])[:5]
            ],
            "keyword_results": [
                _compact_context_item(r)
                for r in retrieval.get("keyword_results", [])[:3]
            ],
        },
    }


def _compact_prev_chapter(ch: dict[str, Any]) -> dict[str, Any]:
    """Keep the previous chapter text. If over 8000 chars, keep the TAIL
    (the ending is what connects to the current chapter)."""
    text = str(ch.get("text", ""))
    if len(text) > 8000:
        text = text[-8000:]
    return {
        "chapter_id": ch.get("chapter_id"),
        "title": ch.get("title", ""),
        "text": text,
    }


def _compact_context_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    compact: dict[str, Any] = {}
    for key in ["chapter_id", "title", "chapter_title", "short_summary", "summary", "text", "content"]:
        if key in item:
            value = item[key]
            if not isinstance(value, str):
                compact[key] = value
            elif key in ("text", "content"):
                # Full chapter body for continuity — cap at 6000 chars
                # to keep the prompt from exploding on very long chapters.
                compact[key] = value[:6000]
            elif key == "short_summary":
                compact[key] = value[:400]
            else:
                compact[key] = value[:200]
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

def _extract_title_from_text(text: str) -> str:
    """Extract chapter title from the first heading line in draft text."""
    import re as _re
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _re.match(r"^#\s*第[一二三四五六七八九十\d]+章\s*(.+)", line)
        if m:
            return m.group(1).strip()
        m = _re.match(r"^#\s*(.+)", line)
        if m:
            return m.group(1).strip()
        # If first non-empty line isn't a heading, use it as title
        return line[:40]
    return ""
