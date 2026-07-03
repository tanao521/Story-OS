from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


QUALITY_VERSION = "1.6"
SCORE_KEYS = [
    "story_goal_alignment",
    "continuity",
    "character_voice",
    "style_naturalness",
    "anti_ai_style",
    "pacing",
    "hook_strength",
    "readability",
]
SUMMARY_WORDS = ["显然", "总之", "可以看出", "以下是", "本章主要", "接下来"]
AI_PHRASES = ["作为AI", "作为 AI", "我无法"]


def count_chinese_chars(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def detect_ai_style_patterns(text: str) -> dict[str, Any]:
    not_but_count = min(text.count("不是"), text.count("而是"))
    no_but_count = min(text.count("他没有") + text.count("她没有"), text.count("而是"))
    dash_count = text.count("——") + text.count("--") + text.count("—")
    summary_words = [word for word in SUMMARY_WORDS if word in text]
    ai_phrases = [phrase for phrase in AI_PHRASES if phrase in text]
    warnings: list[str] = []
    if not_but_count:
        warnings.append("出现“不是/而是”对照句式。")
    if no_but_count:
        warnings.append("出现“他/她没有……而是……”句式。")
    if dash_count > 3:
        warnings.append("破折号数量偏多。")
    if summary_words:
        warnings.append("出现总结或说明文倾向词。")
    if ai_phrases:
        warnings.append("出现 AI 自述类短语。")
    return {
        "not_but_count": not_but_count,
        "dash_count": dash_count,
        "summary_words": summary_words,
        "ai_phrases": ai_phrases,
        "warnings": warnings,
    }


def extract_dialogue_lines(text: str) -> list[str]:
    lines = re.findall(r"[“「](.*?)[”」]", text, flags=re.S)
    return [line.strip() for line in lines if line.strip()]


def evaluate_text_by_rules(
    text: str,
    chapter_plan: dict[str, Any],
    story_spec: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    del story_spec
    ai_patterns = detect_ai_style_patterns(text)
    dialogue_lines = extract_dialogue_lines(text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    sentences = [part for part in re.split(r"[。！？!?]", text) if part.strip()]
    chinese_count = count_chinese_chars(text)
    chapter_goal = str(chapter_plan.get("chapter_goal", ""))
    ending_hook = str(chapter_plan.get("pacing_design", {}).get("ending_hook", ""))
    contains_goal = _contains_keywords(text, chapter_goal)
    contains_hook = _contains_keywords(text[-500:], ending_hook)
    too_short = chinese_count < 500
    looks_like_json = _looks_like_json(text)
    looks_like_summary = any(word in text[:300] for word in ["以下是", "本章主要", "接下来"])
    too_many_dashes = ai_patterns["dash_count"] > 3
    too_many_ai_patterns = ai_patterns["not_but_count"] > 2 or bool(ai_patterns["ai_phrases"])
    long_sentence_ratio = _ratio([len(item) > 80 for item in sentences])
    long_paragraph_ratio = _ratio([len(item) > 500 for item in paragraphs])
    required_characters = chapter_plan.get("required_context", {}).get("characters_to_use", [])
    character_names = [
        str(item.get("name", ""))
        for item in required_characters
        if isinstance(item, dict) and item.get("name")
    ]
    used_character_count = sum(1 for name in character_names if name and name in text)
    continuity_terms = _continuity_terms(world_bible, state)
    continuity_hits = sum(1 for term in continuity_terms if term and term in text)

    scores = {
        "story_goal_alignment": _score_bool(contains_goal, 0.55),
        "continuity": _clamp(0.76 + min(continuity_hits, 3) * 0.04),
        "character_voice": _character_voice_score(dialogue_lines, character_names, used_character_count),
        "style_naturalness": _style_score(looks_like_summary, len(paragraphs), ai_patterns),
        "anti_ai_style": _anti_ai_score(ai_patterns),
        "pacing": _pacing_score(paragraphs, text),
        "hook_strength": _score_bool(contains_hook, 0.55),
        "readability": _readability_score(long_sentence_ratio, long_paragraph_ratio, text),
    }
    if too_short:
        scores = {key: _clamp(value - 0.12) for key, value in scores.items()}
    if looks_like_json:
        scores = {key: min(value, 0.3) for key, value in scores.items()}

    flags = _build_flags(
        ai_patterns,
        contains_goal,
        contains_hook,
        too_short,
        looks_like_summary,
        looks_like_json,
        dialogue_lines,
    )
    suggestions = _build_suggestions(flags, scores)
    overall_score = _clamp(sum(scores.values()) / len(scores))
    return {
        "overall_score": overall_score,
        "scores": scores,
        "flags": flags,
        "suggestions": suggestions,
        "reader_simulation": {
            "engagement_score": _clamp((scores["pacing"] + scores["hook_strength"]) / 2),
            "retention_risk": _clamp(1 - overall_score),
            "emotion_curve": [],
            "likely_reaction": _likely_reaction(overall_score),
        },
        "checks": {
            "contains_chapter_goal": contains_goal,
            "contains_ending_hook": contains_hook,
            "too_short": too_short,
            "too_many_dashes": too_many_dashes,
            "too_many_ai_patterns": too_many_ai_patterns,
            "looks_like_summary": looks_like_summary,
            "looks_like_json": looks_like_json,
        },
    }


def build_quality_report(
    source: dict[str, Any],
    source_type: str,
    source_version: int,
    source_path: str,
    chapter_plan: dict[str, Any],
    story_spec: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    use_llm: bool = False,
) -> dict[str, Any]:
    text = str(source.get("manual_text") or source.get("edited_text") or source.get("draft_text", ""))
    evaluated = evaluate_text_by_rules(text, chapter_plan, story_spec, characters, world_bible, state)
    warnings = ["DeepSeek 质量评估未启用或不可用，已使用本地规则评估。"] if use_llm else []
    generation = {
        "mode": "local_rule",
        "model": "local_rule",
        "fallback_used": bool(use_llm),
        "warnings": warnings,
    }
    return {
        "quality_version": QUALITY_VERSION,
        "chapter_id": int(source.get("chapter_id", chapter_plan.get("chapter_id", 1)) or 1),
        "source_type": source_type,
        "source_version": source_version,
        "source_path": source_path,
        "overall_score": evaluated["overall_score"],
        "scores": evaluated["scores"],
        "flags": evaluated["flags"],
        "suggestions": evaluated["suggestions"],
        "reader_simulation": evaluated["reader_simulation"],
        "checks": evaluated["checks"],
        "generation": generation,
    }


def render_quality_report_markdown(report: dict[str, Any]) -> str:
    label = f"{report.get('source_type', '')}_v{int(report.get('source_version', 0) or 0):03d}"
    score_rows = "\n".join(
        f"| {key} | {value:.2f} |" for key, value in report.get("scores", {}).items()
    )
    flag_rows = "\n".join(
        f"- [{item.get('severity', '')}] {item.get('type', '')}: {item.get('message', '')}"
        for item in report.get("flags", [])
    ) or "无"
    suggestions = "\n".join(f"- {item}" for item in report.get("suggestions", [])) or "无"
    checks = "\n".join(
        f"- {key}: {value}" for key, value in report.get("checks", {}).items()
    )
    reader = report.get("reader_simulation", {})
    generation = report.get("generation", {})
    return f"""# 第{report.get("chapter_id", "")}章质量评估：{label}

## 总分

{report.get("overall_score", 0):.2f}

## 分项评分

| 维度 | 分数 |
|---|---|
{score_rows}

## 问题标记

{flag_rows}

## 修改建议

{suggestions}

## 读者模拟

- 参与度：{reader.get("engagement_score", 0):.2f}
- 弃读风险：{reader.get("retention_risk", 0):.2f}
- 可能反应：{reader.get("likely_reaction", "")}

## 检查项

{checks}

## 生成信息

- mode: {generation.get("mode", "")}
- model: {generation.get("model", "")}
- fallback_used: {generation.get("fallback_used", False)}
- warnings: {generation.get("warnings", [])}
"""


def save_quality_report(report: dict[str, Any], data_dir: str | Path = "data") -> tuple[str, str]:
    json_path, markdown_path = quality_report_paths(
        int(report.get("chapter_id", 1) or 1),
        str(report.get("source_type", "")),
        int(report.get("source_version", 0) or 0),
        data_dir,
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_quality_report_markdown(report), encoding="utf-8")
    return json_path.as_posix(), markdown_path.as_posix()


def quality_report_paths(
    chapter_id: int,
    source_type: str,
    source_version: int,
    data_dir: str | Path = "data",
) -> tuple[Path, Path]:
    stem = f"chapter_{chapter_id:03d}_{source_type}_v{source_version:03d}_quality"
    directory = Path(data_dir) / "quality_reports"
    return directory / f"{stem}.json", directory / f"{stem}.md"


def load_quality_report(
    chapter_id: int,
    source_type: str,
    source_version: int,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    json_path, _ = quality_report_paths(chapter_id, source_type, source_version, data_dir)
    if not json_path.exists():
        return {}
    return json.loads(json_path.read_text(encoding="utf-8"))


def quality_summary_from_report(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    return {
        "overall_score": report.get("overall_score", 0),
        "ai_risk": _risk_from_flags(report, "anti_ai_style"),
        "continuity_risk": _risk_from_score(report, "continuity"),
        "hook_strength": _hook_label(report),
        "markdown_path": quality_report_paths(
            int(report.get("chapter_id", 1) or 1),
            str(report.get("source_type", "")),
            int(report.get("source_version", 0) or 0),
        )[1].as_posix(),
    }


def _contains_keywords(text: str, source: str) -> bool:
    if not source:
        return True
    keywords = [part for part in re.split(r"[\s，。；：、,.!?！？]+", source) if len(part) >= 2]
    return any(keyword in text for keyword in keywords[:5]) if keywords else True


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if not ((stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))):
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def _ratio(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _score_bool(value: bool, false_score: float) -> float:
    return 0.88 if value else false_score


def _character_voice_score(dialogue_lines: list[str], character_names: list[str], used_count: int) -> float:
    score = 0.78
    if character_names and used_count == 0:
        score -= 0.15
    if not dialogue_lines:
        score -= 0.18
    if dialogue_lines and all(len(line) > 60 for line in dialogue_lines):
        score -= 0.12
    if any("因为" in line and "所以" in line for line in dialogue_lines):
        score -= 0.08
    return _clamp(score)


def _style_score(looks_like_summary: bool, paragraph_count: int, patterns: dict[str, Any]) -> float:
    score = 0.84
    if looks_like_summary:
        score -= 0.22
    if paragraph_count < 3:
        score -= 0.12
    if patterns["summary_words"]:
        score -= 0.08 * len(patterns["summary_words"])
    return _clamp(score)


def _anti_ai_score(patterns: dict[str, Any]) -> float:
    score = 0.9
    score -= min(patterns["not_but_count"], 5) * 0.06
    score -= min(patterns["dash_count"], 8) * 0.025
    score -= len(patterns["summary_words"]) * 0.05
    score -= len(patterns["ai_phrases"]) * 0.25
    return _clamp(score)


def _pacing_score(paragraphs: list[str], text: str) -> float:
    score = 0.78
    action_terms = ["走", "看", "推", "跑", "打开", "停", "听", "抓", "退", "冲"]
    conflict_terms = ["冲突", "危险", "压力", "争", "挡", "威胁", "失败", "代价"]
    if len(paragraphs) >= 5:
        score += 0.06
    if any(term in text for term in action_terms):
        score += 0.06
    if any(term in text for term in conflict_terms):
        score += 0.06
    if len(paragraphs) <= 2:
        score -= 0.12
    return _clamp(score)


def _readability_score(long_sentence_ratio: float, long_paragraph_ratio: float, text: str) -> float:
    score = 0.86
    score -= long_sentence_ratio * 0.25
    score -= long_paragraph_ratio * 0.2
    if text.count("，") > max(20, count_chinese_chars(text) // 20):
        score -= 0.05
    return _clamp(score)


def _build_flags(
    patterns: dict[str, Any],
    contains_goal: bool,
    contains_hook: bool,
    too_short: bool,
    looks_like_summary: bool,
    looks_like_json: bool,
    dialogue_lines: list[str],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if patterns["not_but_count"] > 1 or patterns["dash_count"] > 3 or patterns["ai_phrases"]:
        flags.append({
            "type": "anti_ai_style",
            "severity": "medium" if not patterns["ai_phrases"] else "high",
            "message": "出现较多 AI 味或模板化表达。",
            "evidence": patterns["warnings"],
        })
    if not contains_goal:
        flags.append({"type": "story_goal_alignment", "severity": "medium", "message": "未明显体现章节目标。", "evidence": []})
    if not contains_hook:
        flags.append({"type": "hook_strength", "severity": "medium", "message": "结尾钩子较弱或未出现。", "evidence": []})
    if too_short:
        flags.append({"type": "readability", "severity": "medium", "message": "文本长度偏短。", "evidence": []})
    if looks_like_summary:
        flags.append({"type": "style_naturalness", "severity": "medium", "message": "文本更像说明或大纲。", "evidence": []})
    if looks_like_json:
        flags.append({"type": "style_naturalness", "severity": "high", "message": "文本看起来像 JSON。", "evidence": []})
    if not dialogue_lines:
        flags.append({"type": "character_voice", "severity": "low", "message": "缺少可识别台词，人物声音较弱。", "evidence": []})
    return flags


def _build_suggestions(flags: list[dict[str, Any]], scores: dict[str, float]) -> list[str]:
    suggestions: list[str] = []
    flag_types = {item.get("type") for item in flags}
    if "anti_ai_style" in flag_types:
        suggestions.append("减少对照句式、破折号和总结性表达，改用动作或环境细节。")
    if "hook_strength" in flag_types:
        suggestions.append("结尾钩子可以更具体，让读者明确感到下一步风险。")
    if "character_voice" in flag_types or scores.get("character_voice", 1) < 0.7:
        suggestions.append("增加更短、更有差异的人物台词。")
    if "story_goal_alignment" in flag_types:
        suggestions.append("补强与本章目标直接相关的行动或冲突。")
    if not suggestions:
        suggestions.append("整体可用，人工审核时重点检查人物状态和伏笔连续性。")
    return suggestions


def _continuity_terms(world_bible: dict[str, Any], state: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for item in world_bible.get("continuity_rules", []):
        terms.append(str(item.get("rule", item)) if isinstance(item, dict) else str(item))
    world = state.get("world", {})
    if isinstance(world, dict):
        terms.extend(str(item) for item in world.get("rules", []) if item)
    foreshadows = state.get("foreshadows", [])
    if isinstance(foreshadows, list):
        terms.extend(str(item.get("content", "")) for item in foreshadows if isinstance(item, dict))
    return [term for term in terms if term]


def _likely_reaction(score: float) -> str:
    if score >= 0.8:
        return "读者大概率能顺畅读完，并愿意进入下一章。"
    if score >= 0.65:
        return "读者能理解剧情，但部分段落可能需要人工打磨。"
    return "读者可能觉得推进不足或文本不够自然。"


def _risk_from_flags(report: dict[str, Any], flag_type: str) -> str:
    severities = [
        str(item.get("severity", ""))
        for item in report.get("flags", [])
        if item.get("type") == flag_type
    ]
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    if "low" in severities:
        return "low"
    return "low"


def _risk_from_score(report: dict[str, Any], key: str) -> str:
    score = float(report.get("scores", {}).get(key, 0.0) or 0.0)
    if score < 0.55:
        return "high"
    if score < 0.7:
        return "medium"
    return "low"


def _hook_label(report: dict[str, Any]) -> str:
    score = float(report.get("scores", {}).get("hook_strength", 0.0) or 0.0)
    if score >= 0.8:
        return "良好"
    if score >= 0.65:
        return "一般"
    return "偏弱"


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 2)
