from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.chapter_archive import is_memory_chapter_active


CONTEXT_JSON_PATH = Path("data/context/current_context.json")
CONTEXT_MARKDOWN_PATH = Path("data/context/current_context.md")


def build_working_context(
    state: dict[str, Any],
    memory_index: dict[str, Any],
    query: str = "",
    story_spec: dict[str, Any] | None = None,
    characters: dict[str, Any] | None = None,
    world_bible: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_chapter = int(state.get("current_chapter", 0) or 0)
    total_committed = len(memory_index.get("chapters", [])) if isinstance(memory_index.get("chapters"), list) else 0

    # ── Layer 1: Global Memory (always included, compact) ──────────────
    global_memory = _build_global_memory(story_spec or {}, characters or {}, world_bible or {}, state)

    # ── Layer 2: Recent Memory (1 full prev chapter + 3 summaries) ─────
    recent_chapters = get_recent_chapters(memory_index, current_chapter, limit=3)
    recent_ids = [int(ch["chapter_id"]) for ch in recent_chapters if "chapter_id" in ch]

    # Split: the LATEST chapter as full text, the rest as summaries only
    prev_chapter_full: dict[str, Any] | None = None
    recent_summaries: list[dict[str, Any]] = []
    if recent_chapters:
        # Newest = the highest chapter_id = last element (they're sorted asc)
        prev_chapter_full = recent_chapters[-1]
        # Older (up to 2) → summaries
        for ch in recent_chapters[:-1]:
            cid = ch.get("chapter_id", 0)
            recent_summaries.append(_load_chapter_summary(cid, ch, memory_index))
        # Also add the newest chapter's summary for quick reference
        if prev_chapter_full:
            cid = prev_chapter_full.get("chapter_id", 0)
            recent_summaries.insert(0, _load_chapter_summary(cid, prev_chapter_full, memory_index))

    # Supplement with summaries from older chapters if < 3 total
    if len(recent_summaries) < 3:
        extra_summaries = retrieve_old_summaries(
            memory_index, current_chapter, "", recent_ids, max_results=3 - len(recent_summaries),
        )
        recent_summaries.extend(extra_summaries)

    retrieved_summaries = retrieve_old_summaries(
        memory_index, current_chapter, query, recent_ids, max_results=5,
    )

    # ── Layer 3: Retrieval Memory (vector search, on-demand) ───────────
    vector_retrieved: list[dict[str, Any]] = []
    retrieval_mode = "keyword"
    try:
        from system.vector_memory import is_available, search_similar

        if is_available() and query:
            retrieval_mode = "keyword_plus_vector"
            vector_retrieved = search_similar(query, max_results=5)
    except Exception:
        pass

    warnings: list[str] = [
        f"章节原文缺失：chapter_{ch.get('chapter_id', ''):03d}"
        for ch in recent_chapters if ch.get("missing")
    ]

    return {
        "context_version": "1.0",
        "mode": "three_tier_memory",
        "current_chapter": current_chapter,
        "next_chapter_id": current_chapter + 1,
        "global_memory": global_memory,
        "recent_memory": {
            "previous_chapter_full": prev_chapter_full,
            "recent_summaries": recent_summaries,
        },
        "retrieval_memory": {
            "vector_results": vector_retrieved,
            "keyword_results": retrieved_summaries,
            "mode": retrieval_mode,
        },
        "state_snapshot": build_state_snapshot(state),
        "memory_budget": {
            "global_memory_chars": _estimate_chars(global_memory),
            "prev_chapter_chars": len(str(prev_chapter_full.get("text", ""))) if prev_chapter_full else 0,
            "recent_summaries_count": len(recent_summaries),
            "vector_retrieved_count": len(vector_retrieved),
            "keyword_retrieved_count": len(retrieved_summaries),
            "total_committed": total_committed,
        },
        "warnings": warnings,
        # ── backwards-compat aliases ───────────────────────────────────
        "recent_chapters": recent_chapters,
        "retrieved_summaries": retrieved_summaries,
        "vector_retrieved_memories": vector_retrieved,
        "working_context_policy": {
            "recent_raw_chapters": 3,
            "older_chapters": "summary_only",
            "retrieval": retrieval_mode,
        },
    }


def _build_global_memory(
    story_spec: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Build the compact global memory blob — always sent, never truncated."""
    constraints = story_spec.get("writing_constraints", {}) if isinstance(story_spec, dict) else {}
    if not isinstance(constraints, dict):
        constraints = {}
    # protagonist goals: from main characters' core_desire
    main_chars = characters.get("main_characters", []) if isinstance(characters, dict) else []
    protagonist_goals: list[str] = []
    for mc in main_chars[:3]:
        if isinstance(mc, dict) and mc.get("core_desire"):
            protagonist_goals.append(f"{mc.get('name', '')}: {mc['core_desire']}")
    # world rules
    world_rules: list[str] = []
    if isinstance(world_bible, dict):
        for r in world_bible.get("core_rules", [])[:5]:
            if isinstance(r, dict) and r.get("rule"):
                world_rules.append(r["rule"])
        for r in world_bible.get("continuity_rules", [])[:3]:
            if isinstance(r, str):
                world_rules.append(r)
    return {
        "title": str(story_spec.get("title", "")),
        "genre": str(story_spec.get("genre", "")),
        "tone": str(story_spec.get("tone", "")),
        "writing_style": str(story_spec.get("writing_style", "")),
        "narration": str(story_spec.get("narration", "")),
        "world_style": str(world_bible.get("world_style", story_spec.get("world_style", ""))),
        "protagonist_goals": protagonist_goals,
        "world_rules": world_rules,
        "core_appeal": story_spec.get("focus", []) if isinstance(story_spec.get("focus"), list) else [],
        "forbidden": constraints.get("must_avoid") or story_spec.get("avoid", []) or [],
        "anti_ai_rules": constraints.get("ai_style_limits") or story_spec.get("anti_ai_style_rules", []) or [],
        "current_chapter": state.get("current_chapter", 0),
        "open_foreshadows_count": len([
            f for f in (state.get("foreshadows") or [])
            if isinstance(f, dict) and f.get("status") in {"open", "planned"}
        ]) if isinstance(state.get("foreshadows"), list) else 0,
    }


def _load_chapter_summary(
    chapter_id: int,
    chapter_entry: dict[str, Any],
    memory_index: dict[str, Any],
) -> dict[str, Any]:
    """Return a compact summary dict for a chapter."""
    raw_path = str(chapter_entry.get("summary_path", ""))
    data: dict[str, Any] = {}
    if raw_path:
        summary_path = Path(raw_path)
        if summary_path.exists():
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {
        "chapter_id": chapter_id,
        "title": str(data.get("chapter_title", chapter_entry.get("title", ""))),
        "short_summary": str(data.get("short_summary", chapter_entry.get("short_summary", ""))),
        "key_events": data.get("key_events", []) if isinstance(data.get("key_events"), list) else [],
        "memory_tags": data.get("memory_tags", chapter_entry.get("memory_tags", [])) if isinstance(data.get("memory_tags"), list) else [],
    }


def _estimate_chars(obj: Any) -> int:
    """Quick character count for budget tracking."""
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return 0


def get_recent_chapters(
    memory_index: dict[str, Any],
    current_chapter: int,
    limit: int = 3,
) -> list[dict[str, Any]]:
    chapters = _chapter_entries(memory_index)
    eligible = [
        chapter
        for chapter in chapters
        if int(chapter.get("chapter_id", 0) or 0) <= current_chapter
    ]
    recent = sorted(eligible, key=lambda item: int(item.get("chapter_id", 0) or 0), reverse=True)[:limit]
    result: list[dict[str, Any]] = []
    for chapter in sorted(recent, key=lambda item: int(item.get("chapter_id", 0) or 0)):
        path = Path(str(chapter.get("chapter_path", "")))
        item = {
            "chapter_id": chapter.get("chapter_id", 0),
            "title": chapter.get("title", ""),
            "chapter_path": chapter.get("chapter_path", ""),
            "summary_path": chapter.get("summary_path", ""),
            "short_summary": chapter.get("short_summary", ""),
            "memory_tags": chapter.get("memory_tags", []),
            "text": "",
        }
        if path.exists():
            item["text"] = path.read_text(encoding="utf-8")
        else:
            item["missing"] = True
        result.append(item)
    return result


def retrieve_old_summaries(
    memory_index: dict[str, Any],
    current_chapter: int,
    query: str,
    exclude_recent_ids: list[int],
    max_results: int = 5,
) -> list[dict[str, Any]]:
    excluded = set(exclude_recent_ids)
    old_chapters = [
        chapter
        for chapter in _chapter_entries(memory_index)
        if int(chapter.get("chapter_id", 0) or 0) <= current_chapter
        and int(chapter.get("chapter_id", 0) or 0) not in excluded
    ]
    keywords = _keywords(query)
    scored = []
    for chapter in old_chapters:
        summary = _load_summary_entry(chapter)
        matched = _matched_keywords(summary, keywords)
        score = len(matched)
        if not keywords:
            score = len(summary.get("memory_tags", []))
        scored.append((score, int(summary.get("chapter_id", 0) or 0), matched, summary))

    if keywords:
        scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {
            "chapter_id": summary.get("chapter_id", 0),
            "title": summary.get("title", summary.get("chapter_title", "")),
            "summary_path": summary.get("summary_path", ""),
            "short_summary": summary.get("short_summary", ""),
            "memory_tags": summary.get("memory_tags", []),
            "matched_keywords": matched,
        }
        for _, _, matched, summary in scored[:max_results]
    ]


def build_state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
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


def render_context_markdown(context: dict[str, Any]) -> str:
    policy = context.get("working_context_policy", {})
    budget = context.get("memory_budget", {})
    return f"""# 当前写作上下文包

## 记忆策略

- 最近原文章节数：{policy.get("recent_raw_chapters", 3)}
- 旧章节策略：{policy.get("older_chapters", "")}
- 检索方式：{policy.get("retrieval", "")}

## 当前状态摘要

- 当前章节：{context.get("current_chapter", 0)}
- 下一章：{context.get("next_chapter_id", 1)}
- 当前阶段：{context.get("state_snapshot", {}).get("current_stage", "")}

## 最近3章原文

{_render_recent_chapters(context.get("recent_chapters", []))}

## 检索命中的旧章节摘要

{_render_retrieved_summaries(context.get("retrieved_summaries", []))}

## 记忆预算

- 最近原文章节：{budget.get("recent_chapters_count", 0)}
- 检索摘要数量：{budget.get("retrieved_summaries_count", 0)}
- 排除原文历史章节数：{budget.get("raw_history_excluded_count", 0)}

## 警告

{_render_list(context.get("warnings", []))}
"""


def save_current_context(context: dict[str, Any]) -> tuple[str, str]:
    CONTEXT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_JSON_PATH.write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    CONTEXT_MARKDOWN_PATH.write_text(render_context_markdown(context), encoding="utf-8")
    return CONTEXT_JSON_PATH.as_posix(), CONTEXT_MARKDOWN_PATH.as_posix()


def _chapter_entries(memory_index: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = memory_index.get("chapters", [])
    if not isinstance(chapters, list):
        return []
    return [chapter for chapter in chapters if isinstance(chapter, dict) and is_memory_chapter_active(chapter)]


def _load_summary_entry(chapter: dict[str, Any]) -> dict[str, Any]:
    summary_path = Path(str(chapter.get("summary_path", "")))
    if summary_path.exists():
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        data = {}
    return {
        "chapter_id": data.get("chapter_id", chapter.get("chapter_id", 0)),
        "title": chapter.get("title", data.get("chapter_title", "")),
        "chapter_title": data.get("chapter_title", chapter.get("title", "")),
        "summary_path": chapter.get("summary_path", ""),
        "short_summary": data.get("short_summary", chapter.get("short_summary", "")),
        "memory_tags": data.get("memory_tags", chapter.get("memory_tags", [])),
    }


def _keywords(query: str) -> list[str]:
    cleaned = query.replace("，", " ").replace("。", " ").replace("；", " ")
    return [item.strip() for item in cleaned.split() if len(item.strip()) >= 2]


def _matched_keywords(summary: dict[str, Any], keywords: list[str]) -> list[str]:
    haystack = " ".join(
        [
            str(summary.get("title", "")),
            str(summary.get("chapter_title", "")),
            str(summary.get("short_summary", "")),
            " ".join(str(tag) for tag in summary.get("memory_tags", [])),
        ]
    )
    return [keyword for keyword in keywords if keyword in haystack]


def _render_recent_chapters(chapters: Any) -> str:
    if not isinstance(chapters, list) or not chapters:
        return "无"
    sections = []
    for chapter in chapters:
        missing = "（原文缺失）" if chapter.get("missing") else ""
        sections.append(
            f"### 第{chapter.get('chapter_id', '')}章 {chapter.get('title', '')}{missing}\n\n{chapter.get('text', '')}"
        )
    return "\n\n".join(sections)


def _render_retrieved_summaries(summaries: Any) -> str:
    if not isinstance(summaries, list) or not summaries:
        return "无"
    return "\n\n".join(
        f"""### 第{item.get("chapter_id", "")}章 {item.get("title", "")}

- 摘要：{item.get("short_summary", "")}
- 标签：{", ".join(str(tag) for tag in item.get("memory_tags", []))}
- 命中关键词：{", ".join(str(keyword) for keyword in item.get("matched_keywords", []))}"""
        for item in summaries
    )


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)
