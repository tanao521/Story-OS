"""Quality-driven refinement with full 3-tier memory context.

Separate module to avoid corrupting draft_editor.py's encoding.
"""

from __future__ import annotations

import json as _json
from typing import Any

from core.draft_writer import clean_ai_style
from core.llm_api_model import generate_with_api_model, load_api_model_settings


def _count_chars(text: str) -> int:
    return len([c for c in text if not c.isspace()])


def _strip_llm_wrapper(text: str) -> str:
    """Remove common LLM response wrappers."""
    import re as _re
    t = text.strip()
    t = _re.sub(r'^```[a-zA-Z]*\s*\n', '', t)
    t = _re.sub(r'\n```\s*$', '', t)
    for prefix in [
        '以下是编辑后的正文', '以下是修改后的正文', '以下是润色后的正文',
        '编辑后的正文如下', '修改后的正文如下', '以下是正文',
        'Here is the edited text', 'Edited text:', 'Revised text:',
    ]:
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            if t.startswith('：') or t.startswith(':'):
                t = t[1:].strip()
    return t.strip()


def _text_change_ratio(original: str, revised: str) -> float:
    import difflib
    if not original.strip():
        return 1.0
    orig_lines = original.splitlines()
    rev_lines = revised.splitlines()
    sm = difflib.SequenceMatcher(None, orig_lines, rev_lines)
    return 1.0 - sm.ratio()


def _error_text(exc: BaseException) -> str:
    msg = str(exc).strip()
    return msg[:300] if msg else exc.__class__.__name__


def is_valid_edited_text(text: str, original_text: str, min_chars: int = 500) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if (stripped.startswith("{") and stripped.endswith("}")) or \
       (stripped.startswith("[") and stripped.endswith("]")):
        return False
    for phrase in ["作为AI", "作为 AI", "我无法", "以下是修改建议", "以下是编辑后的正文"]:
        if phrase in stripped:
            return False
    for prefix in ("分析：", "说明：", "修改建议：", "以下是分析", "以下是说明"):
        if stripped.startswith(prefix):
            return False
    if _count_chars(stripped) < min_chars:
        return False
    if original_text and _count_chars(stripped) < int(_count_chars(original_text) * 0.5):
        return False
    return True


def check_edited_draft(
    edited_text: str, original_text: str, chapter_plan: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    valid = is_valid_edited_text(edited_text, original_text)
    if not valid:
        warnings.append("编辑后正文无效。")
    return {"valid_text": valid, "warnings": warnings}


def refine_draft_with_quality_report(
    draft: dict[str, Any],
    chapter_plan: dict[str, Any],
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    quality_report: dict[str, Any],
    working_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refine draft based on quality report, with full 3-tier memory for continuity."""
    original_text = str(
        draft.get("draft_text") or draft.get("edited_text") or
        draft.get("manual_text") or ""
    )

    # ---- Layer 1: global memory ----
    gm = working_context.get("global_memory", {}) if working_context else {}
    # ---- Layer 2: previous CHAPTER (must be committed, read fresh from disk) ----
    current_cid = int(chapter_plan.get("chapter_id", 1) or 1)
    prev_cid = current_cid - 1
    prev_text = ""
    prev_summaries: list[dict[str, Any]] = []
    if prev_cid >= 1:
        from pathlib import Path as _Path
        prev_chapter_path = _Path("data") / "chapters" / f"chapter_{prev_cid:03d}.md"
        if prev_chapter_path.exists():
            full_prev = prev_chapter_path.read_text(encoding="utf-8")
            prev_text = full_prev[-4000:] if len(full_prev) > 4000 else full_prev
        # Also load summaries
        for cid in range(max(1, prev_cid - 2), prev_cid + 1):
            summary_path = _Path("data") / "summaries" / f"chapter_{cid:03d}_summary.json"
            if summary_path.exists():
                try:
                    s = _json.loads(summary_path.read_text(encoding="utf-8"))
                    prev_summaries.append({
                        "chapter": cid,
                        "text": str(s.get("short_summary", ""))[:300],
                    })
                except Exception:
                    pass

    payload = {
        "global_memory": {
            "title": gm.get("title", story_spec.get("title", "")),
            "genre": gm.get("genre", story_spec.get("genre", "")),
            "tone": gm.get("tone", story_spec.get("tone", "")),
            "world_style": gm.get("world_style", world_bible.get("world_style", "")),
            "protagonist_goals": gm.get("protagonist_goals", []),
            "world_rules": gm.get("world_rules", [])[:5],
            "forbidden": gm.get("forbidden", [])[:5],
        },
        "chapter_plan": {
            "chapter_id": chapter_plan.get("chapter_id"),
            "chapter_title": chapter_plan.get("chapter_title"),
            "chapter_goal": chapter_plan.get("chapter_goal"),
            "main_conflict": chapter_plan.get(
                "conflict_design", {}
            ).get("main_conflict", ""),
            "ending_hook": chapter_plan.get("pacing_design", {}).get("ending_hook", ""),
        },
        "previous_chapter_tail": prev_text if prev_text else "(none)",
        "recent_summaries": [
            {"chapter": s.get("chapter_id"), "text": str(s.get("short_summary", ""))[:300]}
            for s in prev_summaries
        ],
        "current_draft": original_text,
        "quality_report": {
            "overall_score": quality_report.get("overall_score"),
            "flags": [
                {"severity": f.get("severity", ""), "message": f.get("message", "")}
                for f in quality_report.get("flags", [])[:10]
                if isinstance(f, dict)
            ],
            "suggestions": quality_report.get("suggestions", [])[:8],
        },
    }

    prompt = (
        "你是中文小说正文校对 Agent。\n"
        "任务：仅修复 quality_report.flags 和 suggestions 中明确指出的问题，不重写整章。\n\n"
        "硬性规则：\n"
        "1. current_draft 是唯一正文基准。保留它的全部情节、人物、顺序、叙述视角、章节标题和结尾；只能在解决具体问题所需的句段做最小改动。\n"
        "2. 不得补写、续写、概括、删减或改述 current_draft 中任何未被问题涉及的内容。\n"
        "3. 必须与 previous_chapter_tail 保持剧情连贯，并遵守 chapter_plan 的 chapter_goal、main_conflict、ending_hook。\n"
        "4. 不能新增角色、世界观规则、关键事件，或跳脱大纲的情节。若报告建议需要这些改动，保留原文，不执行该建议。\n"
        "5. 输出完整章节正文，不输出 JSON、说明、修改记录或 Markdown 代码围栏。\n\n"
        "输入数据：\n"
        + _json.dumps(payload, ensure_ascii=False, indent=2)
    )

    settings = load_api_model_settings()
    try:
        candidate = generate_with_api_model([
            {
                "role": "system",
                "content": (
                    "Continuity editor. Fix ONLY flagged issues. "
                    "Stay consistent with previous chapter. "
                    "Do NOT rewrite or add content. Output full chapter text."
                ),
            },
            {"role": "user", "content": prompt},
        ])
    except Exception as exc:
        raise RuntimeError(f"API call failed: {_error_text(exc)}") from exc

    candidate = _strip_llm_wrapper(candidate)
    edited_text = candidate.strip()

    if not is_valid_edited_text(edited_text, original_text):
        raise RuntimeError("API returned invalid edited text.")

    change_ratio = _text_change_ratio(original_text, edited_text)
    if change_ratio > 0.30:
        raise RuntimeError(
            f"Changed {change_ratio:.0%} of text (max 30%). Rejected."
        )

    checks = check_edited_draft(edited_text, original_text, chapter_plan)
    if not checks.get("valid_text", False):
        joined = "; ".join(checks.get("warnings", []) or [])
        raise RuntimeError(f"Edited text failed checks: {joined}")

    quality_summary = {
        "source_type": quality_report.get("source_type", ""),
        "source_version": quality_report.get("source_version", 0),
        "overall_score": quality_report.get("overall_score"),
        "flags": quality_report.get("flags", [])[:8],
        "suggestions": quality_report.get("suggestions", [])[:8],
    }
    return {
        "edit_version": "1.4",
        "chapter_id": int(draft.get(
            "chapter_id", chapter_plan.get("chapter_id", 1)
        ) or 1),
        "chapter_title": str(draft.get(
            "chapter_title", chapter_plan.get("chapter_title", "")
        )),
        "status": "edited",
        "source_draft_path": str(draft.get(
            "source_draft_path", "data/next_chapter_plan.json"
        )),
        "edited_text": edited_text,
        "actual_word_count": _count_chars(edited_text),
        "editing": {
            "mode": "api_model",
            "model": settings["model"],
            "fallback_used": False,
            "warnings": ["Refined with 3-tier memory context."],
            "quality_refinement": quality_summary,
        },
        "checks": checks,
        "refined_from_quality_report": quality_summary,
    }
