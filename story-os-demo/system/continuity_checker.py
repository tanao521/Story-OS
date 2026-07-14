from __future__ import annotations

import json
import re
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

WINDOW_CHARS = 800


def continuity_content_hash(text: str) -> str:
    return sha256(str(text or "").encode("utf-8")).hexdigest()


def check_chapter_continuity(previous_text: str, current_text: str) -> dict[str, Any]:
    previous_tail = _compact(previous_text, tail=True)
    current_head = _compact(current_text, tail=False)
    if not previous_tail or not current_head:
        raise ValueError("缺少可用于连贯性检查的正文片段。")
    if not str(getattr(config, "DEEPSEEK_API_KEY", "") or "").strip():
        return _local_fallback(previous_tail, current_head, "未配置 DeepSeek。")
    from llm.model_gateway import get_model_gateway
    from llm.model_models import ModelGatewayError
    prompt = (
        "你是中文长篇小说的剧情连贯性审校员。仅评估前一章结尾与当前章开头能否自然衔接，不要改写正文.\n"
        "检查时间地点、人物状态和视角、未解决事件，以及开场是否承接前章结尾.\n"
        "仅返回 JSON：{\"score\":0.0,\"verdict\":\"pass|warning|fail\",\"summary\":\"...\",\"issues\":[\"...\"],\"suggestions\":[\"...\"]}\n\n"
        f"前一章结尾：\n{previous_tail}\n\n当前章开头：\n{current_head}"
    )
    try:
        result = _normalize_result(_parse_json(get_model_gateway().generate_text("continuity_review", prompt, temperature=0.1, prompt_id="continuity_review")), previous_tail, current_head)
        result["mode"] = "deepseek"
        return result
    except ModelGatewayError as exc:
        return _local_fallback(previous_tail, current_head, str(exc))


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


def _local_fallback(previous_tail: str, current_head: str, reason: str) -> dict[str, Any]:
    previous_terms = set(re.findall(r"[\u4e00-\u9fff]{2,4}", previous_tail))
    current_terms = set(re.findall(r"[\u4e00-\u9fff]{2,4}", current_head))
    shared_terms = sorted(previous_terms & current_terms)
    score = 0.72 if shared_terms else 0.56
    issues = [] if shared_terms else ["未检测到明确重复的人物、地点或事件提示；请人工确认章节开头是否承接上一章结尾。"]
    suggestions = [
        "确认当前章开头的时间、地点和视角是否延续上一章结尾。",
        "必要时在开头补一句人物状态或未解决事件的承接信息。",
    ]
    return {
        "score": score,
        "verdict": "pass" if score >= 0.7 else "warning",
        "summary": "DeepSeek 暂不可用，已按人物/地点/事件线索进行本地连贯性检查。",
        "issues": issues,
        "suggestions": suggestions,
        "window_chars": WINDOW_CHARS,
        "previous_tail_chars": len(previous_tail),
        "current_head_chars": len(current_head),
        "mode": "local_fallback",
        "shared_terms": shared_terms[:8],
        "warnings": [reason],
    }


def continuity_report_paths(
    chapter_id: int,
    source_type: str,
    source_version: int,
    data_dir: str | Path = "data",
) -> tuple[Path, Path]:
    stem = f"chapter_{chapter_id:03d}_{source_type}_v{source_version:03d}_continuity"
    directory = Path(data_dir) / "continuity_reports"
    return directory / f"{stem}.json", directory / f"{stem}.md"


def save_continuity_report(report: dict[str, Any], data_dir: str | Path = "data") -> tuple[str, str]:
    chapter_id = int(report.get("chapter_id", 1) or 1)
    source_type = str(report.get("source_type", ""))
    source_version = int(report.get("source_version", 0) or 0)
    json_path, markdown_path = continuity_report_paths(chapter_id, source_type, source_version, data_dir)
    payload = {
        "continuity_version": "1.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **report,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_continuity_report_markdown(payload), encoding="utf-8")
    return json_path.as_posix(), markdown_path.as_posix()


def load_continuity_report(
    chapter_id: int,
    source_type: str,
    source_version: int,
    data_dir: str | Path = "data",
    content_hash: str = "",
    previous_content_hash: str = "",
) -> dict[str, Any]:
    json_path, _ = continuity_report_paths(chapter_id, source_type, source_version, data_dir)
    direct = _read_continuity_report(json_path)
    if _continuity_report_matches(direct, content_hash, previous_content_hash):
        return direct
    if not content_hash:
        return {}
    directory = Path(data_dir) / "continuity_reports"
    pattern = f"chapter_{chapter_id:03d}_*_continuity.json"
    for candidate in sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True):
        if candidate == json_path:
            continue
        payload = _read_continuity_report(candidate)
        if _continuity_report_matches(payload, content_hash, previous_content_hash):
            return payload
    return {}


def _read_continuity_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _continuity_report_matches(report: dict[str, Any], content_hash: str, previous_content_hash: str) -> bool:
    if not report:
        return False
    if not content_hash:
        return True
    return (
        report.get("content_hash") == content_hash
        and report.get("previous_content_hash") == previous_content_hash
    )


def _render_continuity_report_markdown(report: dict[str, Any]) -> str:
    issues = report.get("issues", [])
    suggestions = report.get("suggestions", [])
    lines = [
        f"# 第 {report.get('chapter_id', '')} 章连贯性检查",
        "",
        f"- 版本：{report.get('source_type', '')}_v{int(report.get('source_version', 0) or 0):03d}",
        f"- 检查时间：{report.get('checked_at', '')}",
        f"- 检查方式：{report.get('mode', '')}",
        f"- 结论：{report.get('verdict', '')}",
        f"- 分数：{report.get('score', '')}",
        "",
        "## 摘要",
        str(report.get("summary", "")),
        "",
        "## 问题",
    ]
    lines.extend(f"- {item}" for item in issues if str(item).strip())
    if not any(str(item).strip() for item in issues):
        lines.append("- 未发现明确问题。")
    lines.append("")
    lines.append("## 建议")
    lines.extend(f"- {item}" for item in suggestions if str(item).strip())
    if not any(str(item).strip() for item in suggestions):
        lines.append("- 无需额外调整。")
    lines.append("")
    return "\n".join(lines)
