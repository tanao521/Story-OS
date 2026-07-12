from __future__ import annotations

import json
from typing import Any

import config

WINDOW_CHARS = 800


def check_chapter_continuity(previous_text: str, current_text: str) -> dict[str, Any]:
    previous_tail = _compact(previous_text, tail=True)
    current_head = _compact(current_text, tail=False)
    if not previous_tail or not current_head:
        raise ValueError("缺少可用于连贯性检查的正文片段。")
    if not str(getattr(config, "DEEPSEEK_API_KEY", "") or "").strip():
        raise RuntimeError("未配置 DeepSeek，无法执行剧情连贯性检查。")
    from llm.deepseek_client import DeepSeekClient
    prompt = (
        "你是中文长篇小说的剧情连贯性审校员。仅评估前一章结尾与当前章开头能否自然衔接，不要改写正文。\n"
        "检查时间地点、人物状态和视角、未解决事件，以及开场是否承接前章结尾。\n"
        "仅返回 JSON：{\"score\":0.0,\"verdict\":\"pass|warning|fail\",\"summary\":\"...\",\"issues\":[\"...\"],\"suggestions\":[\"...\"]}\n\n"
        f"前一章结尾：\n{previous_tail}\n\n当前章开头：\n{current_head}"
    )
    client = DeepSeekClient(str(config.DEEPSEEK_API_KEY), str(config.DEEPSEEK_MODEL), str(config.DEEPSEEK_BASE_URL))
    return _normalize_result(_parse_json(client.chat_text(prompt, temperature=0.1)), previous_tail, current_head)


def _compact(text: str, *, tail: bool) -> str:
    text = str(text or "").strip()
    return text[-WINDOW_CHARS:] if tail and len(text) > WINDOW_CHARS else (text[:WINDOW_CHARS] if len(text) > WINDOW_CHARS else text)


def _parse_json(raw: str) -> dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("连贯性检查未返回有效结果。")
    data = json.loads(raw[start:end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("连贯性检查结果格式无效。")
    return data


def _normalize_result(data: dict[str, Any], previous_tail: str, current_head: str) -> dict[str, Any]:
    try:
        score = max(0.0, min(1.0, float(data.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    verdict = str(data.get("verdict", "warning")).lower()
    if verdict not in {"pass", "warning", "fail"}:
        verdict = "pass" if score >= 0.8 else ("warning" if score >= 0.55 else "fail")
    string_list = lambda value: [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
    return {"score": round(score, 2), "verdict": verdict, "summary": str(data.get("summary", "未提供摘要。")), "issues": string_list(data.get("issues")), "suggestions": string_list(data.get("suggestions")), "window_chars": WINDOW_CHARS, "previous_tail_chars": len(previous_tail), "current_head_chars": len(current_head)}
