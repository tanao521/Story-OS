from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONTEXT_JSON_PATH = Path("data/context/current_context.json")
CONTEXT_MARKDOWN_PATH = Path("data/context/current_context.md")


def build_working_context(
    state: dict[str, Any],
    memory_index: dict[str, Any],
    query: str = "",
) -> dict[str, Any]:
    current_chapter = int(state.get("current_chapter", 0) or 0)
    recent_chapters = get_recent_chapters(memory_index, current_chapter, limit=3)
    recent_ids = [
        int(chapter["chapter_id"])
        for chapter in recent_chapters
        if "chapter_id" in chapter
    ]
    retrieved_summaries = retrieve_old_summaries(
        memory_index,
        current_chapter,
        query,
        recent_ids,
        max_results=5,
    )
    total_committed = len(memory_index.get("chapters", [])) if isinstance(memory_index.get("chapters"), list) else 0
    warnings = [
        f"章节原文缺失：chapter_{chapter.get('chapter_id', ''):03d}"
        for chapter in recent_chapters
        if chapter.get("missing")
    ]

    return {
        "context_version": "0.7",
        "mode": "sliding_window_plus_summary_retrieval",
        "current_chapter": current_chapter,
        "next_chapter_id": current_chapter + 1,
        "working_context_policy": {
            "recent_raw_chapters": 3,
            "older_chapters": "summary_only",
            "retrieval": "rule_based_keyword_search",
        },
        "recent_chapters": recent_chapters,
        "retrieved_summaries": retrieved_summaries,
        "state_snapshot": build_state_snapshot(state),
        "memory_budget": {
            "recent_chapters_count": len(recent_chapters),
            "retrieved_summaries_count": len(retrieved_summaries),
            "raw_history_excluded_count": max(total_committed - len(recent_chapters), 0),
        },
        "warnings": warnings,
    }


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
    return [chapter for chapter in chapters if isinstance(chapter, dict)]


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
