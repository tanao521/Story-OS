from __future__ import annotations

import json
from typing import Any


STORY_SPEC_SCHEMA = {
    "title": "",
    "genre": "",
    "length_type": "",
    "target_word_count": 0,
    "world_style": "",
    "tone": "",
    "writing_style": "",
    "narration": "",
    "character_structure": "",
    "romance_level": "",
    "focus": [],
    "avoid": [],
    "anti_ai_style_rules": [],
    "need_outline": True,
}


def build_story_spec_prompt(raw_answers: dict[str, Any]) -> str:
    return _json_prompt(
        "你是 Story OS 的小说立项规划助手。请根据用户原始回答优化 story_spec。",
        {
            "rules": [
                "只输出 JSON，不要解释，不要 Markdown。",
                "不要写正文。",
                "保留用户原始意图，可以优化措辞。",
                "不能擅自改变类型、篇幅、主角结构。",
            ],
            "schema": STORY_SPEC_SCHEMA,
            "raw_answers": raw_answers,
        },
    )


def build_blueprint_prompt(story_spec: dict[str, Any]) -> str:
    schema = {
        "title": "",
        "blueprint_version": "1.0",
        "genre": "",
        "length_type": "",
        "target_word_count": 0,
        "core_premise": "",
        "main_arc": "",
        "core_conflict": "",
        "ending_direction": "",
        "world_direction": {
            "world_style": "",
            "rules_to_explore": [],
            "important_locations": [],
            "hidden_truths": [],
        },
        "story_phases": [],
        "initial_foreshadow_pool": [],
        "rolling_generation_policy": {
            "mode": "chapter_by_chapter",
            "plan_next_chapter_only": True,
            "working_context_chapters": 3,
            "older_chapters_strategy": "summarize_and_retrieve",
            "state_update_after_each_chapter": True,
        },
    }
    return _json_prompt(
        "你是 Story OS 的全书高层蓝图规划助手。",
        {
            "rules": [
                "只输出 JSON，不要解释，不要 Markdown。",
                "不要生成 chapters 字段。",
                "不要生成几十章列表，只生成 3 到 5 个 story_phases。",
                "采用逐章滚动生成模式。",
            ],
            "schema": schema,
            "story_spec": story_spec,
        },
    )


def build_next_chapter_plan_prompt(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state_snapshot: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> str:
    schema = {
        "plan_version": "1.0",
        "chapter_id": 1,
        "chapter_title": "",
        "estimated_word_count": 3000,
        "chapter_goal": "",
        "phase_position": {},
        "required_context": {},
        "scene_plan": [],
        "conflict_design": {},
        "pacing_design": {},
        "climax_design": {},
        "voice_requirements": {},
        "style_requirements": [],
        "continuity_constraints": [],
        "state_updates_expected": [],
    }
    lightweight_context = None
    if working_context:
        lightweight_context = {
            "mode": working_context.get("mode"),
            "memory_budget": working_context.get("memory_budget"),
            "retrieved_summaries": working_context.get("retrieved_summaries", [])[:5],
            "recent_chapter_titles": [
                {"chapter_id": item.get("chapter_id"), "title": item.get("title")}
                for item in working_context.get("recent_chapters", [])[:3]
                if isinstance(item, dict)
            ],
        }
    return _json_prompt(
        "你是 Story OS 的下一章规划助手。",
        {
            "rules": [
                "只输出 JSON，不要解释，不要 Markdown。",
                "只规划下一章，不写正文，不生成后续章节。",
                "chapter_id 必须是 state.current_chapter + 1。",
                "场景数量 2 到 4 个。",
                "必须考虑 open foreshadows 和 world_bible.continuity_rules。",
                "遵守最近 3 章 + 摘要检索策略，不要塞入全书历史原文。",
            ],
            "schema": schema,
            "story_spec": story_spec,
            "blueprint": blueprint,
            "characters_summary": _characters_summary(characters),
            "world_bible_summary": _world_summary(world_bible),
            "state_snapshot": state_snapshot,
            "working_context": lightweight_context,
        },
    )


def build_edit_draft_prompt(
    draft: dict[str, Any],
    chapter_plan: dict[str, Any],
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state_snapshot: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> str:
    lightweight_context = None
    if working_context:
        lightweight_context = {
            "mode": working_context.get("mode"),
            "recent_chapters": working_context.get("recent_chapters", [])[:3],
            "retrieved_summaries": working_context.get("retrieved_summaries", [])[:5],
            "vector_retrieved_memories": working_context.get("vector_retrieved_memories", [])[:5],
        }
    payload = {
        "draft_text": draft.get("draft_text", ""),
        "chapter_plan": {
            "chapter_id": chapter_plan.get("chapter_id"),
            "chapter_title": chapter_plan.get("chapter_title"),
            "chapter_goal": chapter_plan.get("chapter_goal"),
            "main_conflict": chapter_plan.get("conflict_design", {}).get("main_conflict", ""),
            "ending_hook": chapter_plan.get("pacing_design", {}).get("ending_hook", ""),
            "scene_plan": chapter_plan.get("scene_plan", []),
            "style_requirements": chapter_plan.get("style_requirements", []),
            "continuity_constraints": chapter_plan.get("continuity_constraints", []),
        },
        "story_spec_summary": {
            "title": story_spec.get("title", ""),
            "genre": story_spec.get("genre", ""),
            "tone": story_spec.get("tone", ""),
            "writing_style": story_spec.get("writing_style", ""),
            "narration": story_spec.get("narration", ""),
            "avoid": story_spec.get("avoid", []),
        },
        "blueprint_summary": {
            "main_arc": blueprint.get("main_arc", ""),
            "core_conflict": blueprint.get("core_conflict", ""),
            "ending_direction": blueprint.get("ending_direction", ""),
        },
        "characters_summary": _characters_summary(characters),
        "world_bible_summary": _world_summary(world_bible),
        "state_snapshot": state_snapshot,
        "working_context": lightweight_context,
    }
    return (
        "你是 Story OS 的中文小说正文编辑器。你的任务是编辑当前章草稿，去除 AI 味，修正文风和逻辑问题。\n"
        "你只负责当前章编辑，不负责重新规划剧情。\n\n"
        "硬性禁止：\n"
        "你只能编辑当前章草稿，不能重写剧情方向。\n"
        "不能生成下一章。\n"
        "不能生成大纲。\n"
        "不能添加作者说明。\n"
        "不能输出 JSON。\n"
        "不能解释修改理由。\n"
        "不能改变已确定的世界观规则。\n"
        "不能让角色知道其未经历过的信息。\n"
        "不能擅自回收或新增重大伏笔。\n"
        "不能改变 chapter_plan 中的 chapter_goal、main_conflict、ending_hook。\n\n"
        "重点删除或弱化以下 AI 味：\n"
        "1. 频繁使用“不是A，而是B”\n"
        "2. 频繁使用“他没有X，而是Y”\n"
        "3. 过多破折号\n"
        "4. “显然”“总之”“可以看出”等总结式表达\n"
        "5. 直接解释情绪，例如“他很痛苦”“他很愤怒”\n"
        "6. 所有人说话都像同一个人\n"
        "7. 每段结尾都做总结\n"
        "8. 过度工整的排比\n"
        "9. 过度解释世界观\n"
        "10. 空泛形容词堆叠\n\n"
        "编辑要求：\n"
        "尽量用动作、环境、停顿、物品细节表达情绪。\n"
        "保留小说感，不要改成说明文。\n"
        "不要过度文艺化。\n"
        "不要把正文改短成概要。\n"
        "保持当前章节计划不变，保持人物性格和语言风格，保持世界观规则，不新增重大设定。\n\n"
        "输出要求：\n"
        "只输出编辑后的小说正文文本。\n"
        "不要输出 JSON、Markdown 代码块、修改说明、修改前后对照、作者注释，不要输出“以下是编辑后的正文”。\n\n"
        "输入资料：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _json_prompt(role: str, payload: dict[str, Any]) -> str:
    return f"{role}\n请严格按以下 JSON 要求输出：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def _characters_summary(characters: dict[str, Any]) -> dict[str, Any]:
    return {
        "main_characters": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "role": item.get("role"),
                "core_desire": item.get("core_desire"),
            }
            for item in characters.get("main_characters", [])
            if isinstance(item, dict)
        ]
    }


def _world_summary(world_bible: dict[str, Any]) -> dict[str, Any]:
    return {
        "world_style": world_bible.get("world_style"),
        "genre": world_bible.get("genre"),
        "core_rules": world_bible.get("core_rules", [])[:5],
        "continuity_rules": world_bible.get("continuity_rules", []),
    }
