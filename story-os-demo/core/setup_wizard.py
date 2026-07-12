from __future__ import annotations

from typing import Any

from core.project import ensure_project_structure, resolve_current_project_root


ANTI_AI_STYLE_RULES = [
    "减少‘不是A，而是B’句式",
    "减少破折号",
    "避免总结式表达",
    "避免过度解释人物情绪",
    "用动作和细节代替情绪直述",
]

GENRE_OPTIONS = [
    "末世",
    "都市",
    "玄幻",
    "修仙",
    "科幻",
    "悬疑",
    "奇幻",
    "历史",
    "赛博朋克",
    "其他",
]

LENGTH_OPTIONS = [
    "短篇",
    "中篇",
    "长篇",
    "超长篇",
]

DEFAULT_WORD_COUNTS = {
    "短篇": 8000,
    "中篇": 60000,
    "长篇": 300000,
    "超长篇": 1000000,
}

TONE_OPTIONS = [
    "压抑",
    "轻松",
    "热血",
    "荒诞",
    "黑色幽默",
    "治愈",
    "冷峻",
    "史诗",
    "灰暗但不绝望",
]

WRITING_STYLE_OPTIONS = [
    "电影感",
    "网文爽文",
    "细腻文学",
    "克制冷淡",
    "轻小说",
    "黑色幽默",
    "群像剧",
    "强剧情弱描写",
    "强氛围感",
]

NARRATION_OPTIONS = [
    "第一人称",
    "第三人称有限视角",
    "第三人称全知视角",
    "多视角切换",
]

CHARACTER_STRUCTURE_OPTIONS = [
    "单男主",
    "单女主",
    "男女双主角",
    "群像文",
    "多女主单男主",
    "多男主单女主",
    "无固定主角",
    "其他",
]

ROMANCE_LEVEL_OPTIONS = [
    "无",
    "很弱",
    "轻微",
    "中等",
    "重要主线",
    "后宫/多感情线",
]


def run_setup_wizard() -> dict[str, Any]:
    print("欢迎使用 Story OS Demo v0.1")
    print("现在开始创建你的小说项目。")
    print()

    title = _ask_text("请输入小说标题。如果暂时没有，可以留空：", "未命名小说")
    genre = _ask_choice_or_text("请选择或输入小说类型：", GENRE_OPTIONS)
    length_type = _ask_choice_or_text(
        "你想写短篇、中篇、长篇，还是超长篇？",
        LENGTH_OPTIONS,
    )
    target_word_count = _ask_target_word_count(length_type)
    world_style = _ask_text(
        "你希望世界观是什么风格？可以自由描述：",
        "",
    )
    tone = _ask_choice_or_text("你希望小说整体情绪基调是什么？", TONE_OPTIONS)
    writing_style = _ask_choice_or_text(
        "你希望文笔风格接近什么？",
        WRITING_STYLE_OPTIONS,
    )
    narration = _ask_choice_or_text("你希望使用什么叙事视角？", NARRATION_OPTIONS)
    character_structure = _ask_choice_or_text(
        "你希望人物结构是什么？",
        CHARACTER_STRUCTURE_OPTIONS,
    )
    romance_level = _ask_choice_or_text(
        "感情线在小说中占比如何？",
        ROMANCE_LEVEL_OPTIONS,
    )
    focus = _ask_list("你希望小说重点写什么？可以输入多个关键词，用逗号分隔：")
    avoid = _ask_list("有哪些你不想要的内容或风格？可以留空：")
    anti_ai_style_rules = _ask_anti_ai_style_rules()
    need_outline = _ask_yes_no("是否在下一步生成全书高层蓝图？", default=True)

    return build_story_spec_from_answers({
        "title": title,
        "genre": genre,
        "length_type": length_type,
        "target_word_count": target_word_count,
        "world_style": world_style,
        "tone": tone,
        "writing_style": writing_style,
        "narration": narration,
        "character_structure": character_structure,
        "romance_level": romance_level,
        "focus": focus,
        "avoid": avoid,
        "anti_ai_style_rules": anti_ai_style_rules,
        "need_outline": need_outline,
    })



def build_story_spec_from_answers(raw_answers: dict[str, Any]) -> dict[str, Any]:
    title = str(raw_answers.get("title", "")).strip()
    if not title:
        raise ValueError("title is required")
    genre = str(raw_answers.get("genre", "")).strip()
    custom_genre = str(raw_answers.get("custom_genre", "")).strip()
    if genre in {"其他", "other", "Other"} and custom_genre:
        genre = custom_genre
    if not genre:
        genre = "其他"
    length_type = str(raw_answers.get("length_type", "")).strip() or "长篇"
    target_word_count = _normalize_target_word_count(raw_answers.get("target_word_count"), length_type)
    return {
        "title": title,
        "genre": genre,
        "length_type": length_type,
        "target_word_count": target_word_count,
        "world_style": str(raw_answers.get("world_style", "")).strip(),
        "tone": str(raw_answers.get("tone", "")).strip(),
        "writing_style": str(raw_answers.get("writing_style", "")).strip(),
        "narration": str(raw_answers.get("narration", "")).strip(),
        "character_structure": str(raw_answers.get("character_structure", "")).strip(),
        "romance_level": str(raw_answers.get("romance_level", "")).strip(),
        "focus": _normalize_list(raw_answers.get("focus", [])),
        "avoid": _normalize_list(raw_answers.get("avoid", [])),
        "anti_ai_style_rules": _normalize_list(raw_answers.get("anti_ai_style_rules", [])),
        "need_outline": bool(raw_answers.get("need_outline", True)),
        "use_deepseek": bool(raw_answers.get("use_deepseek", False)),
    }


def create_story_project(raw_answers: dict[str, Any], data_dir: str = "data") -> dict[str, str]:
    import json
    from pathlib import Path

    story_spec = build_story_spec_from_answers(raw_answers)
    state = build_initial_state(story_spec)
    data_path = Path(data_dir)
    project_root = resolve_current_project_root(project_root=data_path.parent if data_path.name == "data" else Path.cwd())
    root = project_root / data_path.name if data_path.name == "data" else data_path
    root.mkdir(parents=True, exist_ok=True)
    story_spec_path = root / "story_spec.json"
    state_path = root / "state.json"
    project_path = root / "project.md"
    story_spec_path.write_text(json.dumps(story_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    project_path.write_text(render_project_markdown(story_spec), encoding="utf-8")
    paths = ensure_project_structure(project_root, form_data={**raw_answers, **story_spec})
    return {
        "project_root": str(project_root),
        "story_spec_path": story_spec_path.as_posix(),
        "state_path": state_path.as_posix(),
        "project_path": project_path.as_posix(),
        "story_blueprint_path": paths["blueprint_path"].as_posix(),
        "plot_state_path": paths["plot_state_path"].as_posix(),
        "chapter_index_path": paths["chapter_index_path"].as_posix(),
        "characters_path": paths["characters_path"].as_posix(),
        "world_rules_path": paths["world_rules_path"].as_posix(),
        "world_bible_path": paths["world_bible_path"].as_posix(),
    }

def _normalize_target_word_count(value: Any, length_type: str) -> int:
    default = DEFAULT_WORD_COUNTS.get(length_type, 300000)
    try:
        count = int(value or default)
    except (TypeError, ValueError):
        return default
    return count if count > 0 else default


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value).replace("，", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]

def build_initial_state(story_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_status": "initialized",
        "current_stage": "setup",
        "current_chapter": 0,
        "characters": {},
        "world": {
            "style": str(story_spec.get("world_style", "")),
            "rules": [],
            "locations": [],
        },
        "plot": {
            "main_arc": "",
            "sub_arcs": [],
            "completed_events": [],
        },
        "foreshadows": [],
        "timeline": [],
        "memory_policy": {
            "working_context_chapters": 3,
            "older_chapters_strategy": "summarize_and_retrieve",
            "use_vector_memory_later": True,
        },
    }


def render_project_markdown(story_spec: dict[str, Any]) -> str:
    focus = _format_markdown_list(story_spec.get("focus", []))
    avoid = _format_markdown_list(story_spec.get("avoid", []))
    anti_ai_rules = _format_markdown_list(story_spec.get("anti_ai_style_rules", []))

    return f"""# 小说项目：{story_spec.get("title", "未命名小说")}

## 基础类型
- 类型：{story_spec.get("genre", "")}
- 篇幅：{story_spec.get("length_type", "")}
- 预计字数：{story_spec.get("target_word_count", 0)}
- 人物结构：{story_spec.get("character_structure", "")}
- 叙事视角：{story_spec.get("narration", "")}

## 世界观风格
{story_spec.get("world_style", "")}

## 情绪基调
{story_spec.get("tone", "")}

## 文笔风格
{story_spec.get("writing_style", "")}

## 剧情重点
{focus}

## 不想要的内容或风格
{avoid}

## 去 AI 味规则
{anti_ai_rules}

## 记忆策略
- 写作时只保留最近 3 章作为工作上下文
- 更早章节压缩成摘要
- 摘要与原文保存到知识库
- 后续需要时通过检索召回
"""


def _ask_text(prompt: str, default: str) -> str:
    answer = input(f"{prompt}\n> ").strip()
    return answer or default


def _ask_choice_or_text(prompt: str, options: list[str]) -> str:
    print(prompt)
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")

    answer = input("> ").strip()
    if answer.isdigit():
        option_index = int(answer)
        if 1 <= option_index <= len(options):
            return options[option_index - 1]

    return answer


def _ask_target_word_count(length_type: str) -> int:
    default_word_count = DEFAULT_WORD_COUNTS.get(length_type, 300000)
    while True:
        answer = input(
            "你预计这本小说大概多少字？可以输入数字，例如 200000。\n"
            f"留空则根据篇幅自动使用 {default_word_count}：\n> "
        ).strip()

        if not answer:
            return default_word_count

        try:
            word_count = int(answer)
        except ValueError:
            print("请输入纯数字，或直接回车使用默认值。")
            continue

        if word_count <= 0:
            print("预计字数需要大于 0。")
            continue

        return word_count


def _ask_list(prompt: str) -> list[str]:
    answer = input(f"{prompt}\n> ").strip()
    if not answer:
        return []

    normalized = answer.replace("，", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _ask_anti_ai_style_rules() -> list[str]:
    enabled = _ask_yes_no("是否启用“去 AI 味限制”？", default=True)
    if not enabled:
        return []

    return ANTI_AI_STYLE_RULES.copy()


def _ask_yes_no(prompt: str, default: bool) -> bool:
    default_text = "yes" if default else "no"
    while True:
        answer = input(f"{prompt}（yes/no，默认 {default_text}）\n> ").strip().lower()
        if not answer:
            return default
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("请输入 yes 或 no，或直接回车使用默认值。")


def _format_markdown_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"

    return "\n".join(f"- {item}" for item in items)
