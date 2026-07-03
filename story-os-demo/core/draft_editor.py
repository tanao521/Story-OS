from __future__ import annotations

import json
import re
from typing import Any

import config
from llm.deepseek_client import DeepSeekClient, DeepSeekError
from llm.prompts import build_edit_draft_prompt


AI_STYLE_WORDS = ["显然", "总之", "可以看出"]
INVALID_EDIT_PHRASES = ["作为AI", "作为 AI", "我无法", "以下是修改建议", "以下是编辑后的正文"]


def build_state_snapshot_for_editing(state: dict[str, Any]) -> dict[str, Any]:
    foreshadows = state.get("foreshadows", [])
    timeline = state.get("timeline", [])
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
        "timeline_tail": timeline[-5:] if isinstance(timeline, list) else [],
        "memory_policy": state.get("memory_policy", {}),
    }


def local_rule_edit(text: str) -> tuple[str, list[str]]:
    edited = text
    warnings: list[str] = []
    for word in AI_STYLE_WORDS:
        if word in edited:
            edited = edited.replace(word, "")
            warnings.append(f"已删除总结式表达：{word}")
    if re.search(r"[-—]{2,}", edited):
        edited = re.sub(r"[-—]{2,}", "，", edited)
        warnings.append("已替换连续破折号。")
    softened = re.sub(r"不是([^，。；\n]{1,24})，?而是", r"\1转为", edited)
    softened = re.sub(r"他没有([^，。；\n]{1,24})，?而是", r"他放下\1，转去", softened)
    if softened != edited:
        edited = softened
        warnings.append("已弱化模板化转折句。")
    return edited.strip(), warnings


def is_valid_edited_text(text: str, original_text: str, min_chars: int = 500) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _looks_like_json(stripped):
        return False
    if any(phrase in stripped for phrase in INVALID_EDIT_PHRASES):
        return False
    if stripped.startswith(("分析：", "说明：", "修改建议：", "以下是分析", "以下是说明")):
        return False
    if _count_chars(stripped) < min_chars:
        return False
    if original_text and _count_chars(stripped) < int(_count_chars(original_text) * 0.5):
        return False
    return True


def edit_draft(
    draft: dict[str, Any],
    chapter_plan: dict[str, Any],
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original_text = str(draft.get("draft_text", ""))
    warnings: list[str] = []
    edited_text = ""
    mode = "local_rule"
    model = "local_rule"
    fallback_used = True

    if config.USE_DEEPSEEK_FOR_EDITING and config.DEEPSEEK_API_KEY:
        prompt = build_edit_draft_prompt(
            draft,
            chapter_plan,
            story_spec,
            blueprint,
            characters,
            world_bible,
            build_state_snapshot_for_editing(state),
            working_context,
        )
        try:
            client = DeepSeekClient(
                api_key=config.DEEPSEEK_API_KEY,
                model=config.DEEPSEEK_MODEL,
                base_url=config.DEEPSEEK_BASE_URL,
            )
            candidate = client.chat_text(prompt, temperature=0.25).strip()
            if is_valid_edited_text(candidate, original_text):
                edited_text = candidate
                mode = "deepseek"
                model = config.DEEPSEEK_MODEL
                fallback_used = False
            else:
                warnings.append("DeepSeek 编辑结果无效，已使用本地规则编辑。")
        except DeepSeekError as exc:
            warnings.append(f"DeepSeek 编辑不可用，已使用本地规则编辑：{_error_summary(exc)}")
    elif config.USE_DEEPSEEK_FOR_EDITING:
        warnings.append("已启用 DeepSeek 编辑，但 DEEPSEEK_API_KEY 未配置，已使用本地规则编辑。")
    else:
        warnings.append("DeepSeek 编辑未启用，已使用本地规则编辑。")

    if not edited_text:
        edited_text, local_warnings = local_rule_edit(original_text)
        warnings.extend(local_warnings)

    checks = check_edited_draft(edited_text, original_text, chapter_plan)
    return {
        "edit_version": "1.2",
        "chapter_id": int(draft.get("chapter_id", chapter_plan.get("chapter_id", 1)) or 1),
        "chapter_title": str(draft.get("chapter_title", chapter_plan.get("chapter_title", ""))),
        "status": "edited",
        "source_draft_path": str(draft.get("source_draft_path", "data/next_chapter_plan.json")),
        "edited_text": edited_text,
        "actual_word_count": _count_chars(edited_text),
        "editing": {
            "mode": mode,
            "model": model,
            "fallback_used": fallback_used,
            "warnings": warnings,
        },
        "checks": checks,
    }


def check_edited_draft(
    edited_text: str,
    original_text: str,
    chapter_plan: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    chapter_goal = str(chapter_plan.get("chapter_goal", ""))
    ending_hook = str(chapter_plan.get("pacing_design", {}).get("ending_hook", ""))
    kept_chapter_goal = _contains_any_keyword(edited_text, chapter_goal)
    kept_ending_hook = _contains_any_keyword(edited_text, ending_hook)
    dash_count = edited_text.count("—") + edited_text.count("--")
    not_but_count = min(edited_text.count("不是"), edited_text.count("而是"))
    reduced_ai_style = (
        dash_count <= 3
        and not_but_count <= 2
        and all(word not in edited_text for word in AI_STYLE_WORDS)
    )
    valid_text = is_valid_edited_text(edited_text, original_text)

    if not kept_chapter_goal:
        warnings.append("未检测到章节目标相关关键词。")
    if not kept_ending_hook:
        warnings.append("未检测到结尾钩子相关内容。")
    if not reduced_ai_style:
        warnings.append("AI 味规则检查未完全通过。")
    if not valid_text:
        warnings.append("编辑后正文无效。")

    return {
        "kept_chapter_goal": kept_chapter_goal,
        "kept_ending_hook": kept_ending_hook,
        "reduced_ai_style": reduced_ai_style,
        "valid_text": valid_text,
        "warnings": warnings,
    }


def render_edited_markdown(edited: dict[str, Any]) -> str:
    editing = edited.get("editing", {})
    checks = edited.get("checks", {})
    warnings = list(editing.get("warnings", [])) + list(checks.get("warnings", []))
    return f"""# 第{edited.get("chapter_id", "")}章 {edited.get("chapter_title", "")}（编辑版）

## 状态

- 版本：v1.2
- 状态：{edited.get("status", "")}
- 编辑模式：{editing.get("mode", "")}
- 是否 fallback：{editing.get("fallback_used", False)}
- 实际字数：{edited.get("actual_word_count", 0)}

## 正文

{edited.get("edited_text", "")}

## 编辑检查

- 是否保留章节目标：{checks.get("kept_chapter_goal", False)}
- 是否保留结尾钩子：{checks.get("kept_ending_hook", False)}
- 是否降低 AI 味：{checks.get("reduced_ai_style", False)}
- 是否有效正文：{checks.get("valid_text", False)}

## 警告

{_render_list(warnings)}
"""


def _contains_any_keyword(text: str, source: str) -> bool:
    if not source:
        return True
    keywords = [part for part in re.split(r"[：，。；、\s]+", source) if len(part) >= 2]
    if not keywords:
        return True
    return any(keyword in text for keyword in keywords[:5])


def _looks_like_json(text: str) -> bool:
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _count_chars(text: str) -> int:
    return len([char for char in text if not char.isspace()])


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _error_summary(error: Exception) -> str:
    message = str(error).strip()
    return message[:200] if message else error.__class__.__name__
