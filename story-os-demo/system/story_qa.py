from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


QA_VERSION = "1.9"
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2, "unknown": 3}


def normalize_question(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise ValueError("问题不能为空")
    return normalized.lower()


def load_story_sources(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    files = {
        "state": root / "state.json",
        "story_spec": root / "story_spec.json",
        "story_blueprint": root / "story_blueprint.json",
        "characters": root / "characters.json",
        "world_bible": root / "world_bible.json",
        "memory_index": root / "memory" / "memory_index.json",
        "todos": root / "todos" / "todos.json",
        "next_chapter_plan": root / "next_chapter_plan.json",
    }
    warnings: list[str] = []
    sources: dict[str, Any] = {"_meta": {"data_dir": root.as_posix(), "warnings": warnings, "paths": {}}}
    for key, path in files.items():
        sources["_meta"]["paths"][key] = path.as_posix()
        if not path.exists():
            sources[key] = {}
            warnings.append(f"缺少文件：{path.as_posix()}")
            continue
        try:
            sources[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sources[key] = {}
            warnings.append(f"JSON 损坏，已跳过：{path.as_posix()}")
    return sources


def extract_state_facts(question: str, sources: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = normalize_question(question)
    facts: list[dict[str, Any]] = []
    if _matches(normalized, ["当前章节", "写到第几章", "现在第几章", "current_chapter"]):
        fact = _current_chapter_fact(sources)
        if fact:
            facts.append(fact)
    if _matches(normalized, ["open 伏笔", "未解决伏笔", "还有哪些伏笔", "未回收伏笔", "伏笔"]):
        fact = _foreshadow_fact(sources)
        if fact:
            facts.append(fact)
    character_fact = _character_fact(normalized, sources)
    if character_fact:
        facts.append(character_fact)
    if _matches(normalized, ["世界观规则", "设定规则", "避难所系统", "规则", "限制"]):
        fact = _world_rule_fact(sources)
        if fact:
            facts.append(fact)
    if _matches(normalized, ["todo", "待办", "任务", "要改什么", "还有什么问题"]):
        fact = _todo_fact(sources)
        if fact:
            facts.append(fact)
    if _matches(normalized, ["质量", "ai味", "问题", "风险", "评分", "审稿"]):
        fact = _quality_fact(normalized, sources)
        if fact:
            facts.append(fact)
    return facts


def search_memory_summaries(
    question: str,
    data_dir: str | Path = "data",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    normalized = normalize_question(question)
    root = Path(data_dir)
    keywords = _keywords(normalized)
    results: list[dict[str, Any]] = []
    for path in sorted((root / "summaries").glob("*.json")):
        data = _read_json(path)
        result = _score_summary(data, path, keywords, normalized)
        if result:
            results.append(result)
    memory_index = _read_json(root / "memory" / "memory_index.json")
    for chapter in memory_index.get("chapters", []) if isinstance(memory_index.get("chapters"), list) else []:
        if not isinstance(chapter, dict):
            continue
        result = _score_memory_index_entry(chapter, root, keywords, normalized)
        if result:
            results.append(result)
    return sorted(results, key=lambda item: float(item.get("score", 0)), reverse=True)[:max_results]


def search_vector_memory_if_available(
    question: str,
    data_dir: str | Path = "data",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    del question, max_results
    sources = load_story_sources(data_dir)
    state = sources.get("state", {})
    vector_config = state.get("vector_memory", {}) if isinstance(state, dict) else {}
    if not isinstance(vector_config, dict) or not vector_config.get("enabled"):
        return []
    report_path = Path(data_dir) / "memory" / "vector_index_report.json"
    if not report_path.exists():
        return []
    report = _read_json(report_path)
    return [{
        "type": "vector",
        "path": report_path.as_posix(),
        "label": "vector_memory",
        "score": 0.3,
        "snippet": str(report.get("summary", "向量记忆已启用，但当前 Demo 未执行真实 Chroma 检索。")),
        "matched_fields": ["vector_index_report"],
    }]


def answer_from_state(question: str, data_dir: str | Path = "data") -> dict[str, Any]:
    normalized = normalize_question(question)
    sources = load_story_sources(data_dir)
    facts = extract_state_facts(normalized, sources)
    if not facts:
        return _qa_result(
            question,
            "我没有在当前 state 中找到明确答案。",
            "state",
            "unknown",
            [],
            warnings=sources.get("_meta", {}).get("warnings", []),
        )
    return _qa_result(
        question,
        "\n\n".join(str(fact.get("answer", "")) for fact in facts),
        "state",
        _best_confidence(facts),
        _merge_sources(facts),
        related=_merge_related(facts),
        warnings=sources.get("_meta", {}).get("warnings", []),
    )


def answer_from_memory(
    question: str,
    data_dir: str | Path = "data",
    use_vector: bool = True,
) -> dict[str, Any]:
    normalized = normalize_question(question)
    summary_results = search_memory_summaries(normalized, data_dir)
    vector_results = search_vector_memory_if_available(normalized, data_dir) if use_vector else []
    results = summary_results + vector_results
    if not results:
        return _qa_result(
            question,
            "我没有在章节摘要或向量记忆中找到明确记录。",
            "memory",
            "unknown",
            [],
        )
    lines = [f"我在章节摘要/记忆中找到 {len(results)} 条相关记录："]
    for index, item in enumerate(results, 1):
        chapter = item.get("chapter_id")
        prefix = f"第{chapter}章" if chapter else str(item.get("label", "记忆"))
        lines.append(f"{index}. {prefix}：{item.get('snippet', '')}")
    return _qa_result(
        question,
        "\n".join(lines),
        "memory",
        "medium",
        [_source_from_search(item) for item in results],
        related={"chapters": [item.get("chapter_id") for item in results if item.get("chapter_id")]},
    )


def answer_from_story(
    question: str,
    data_dir: str | Path = "data",
    use_llm: bool = False,
    use_vector: bool = True,
) -> dict[str, Any]:
    state_result = answer_from_state(question, data_dir)
    memory_result = answer_from_memory(question, data_dir, use_vector=use_vector)
    usable = [item for item in [state_result, memory_result] if item.get("confidence") != "unknown"]
    if not usable:
        return _qa_result(
            question,
            "我没有在当前状态、章节摘要或记忆中找到明确答案。",
            "story",
            "unknown",
            [],
            warnings=list(state_result.get("warnings", [])) + list(memory_result.get("warnings", [])),
        )
    local = _qa_result(
        question,
        "\n\n".join(str(item.get("answer", "")) for item in usable),
        "story",
        _best_confidence(usable),
        _dedupe_sources([source for item in usable for source in item.get("sources", [])]),
        related=_merge_related(usable),
        warnings=list(state_result.get("warnings", [])) + list(memory_result.get("warnings", [])),
    )
    if not use_llm:
        return local
    local["warnings"].append("DeepSeek QA 综合回答未在 v1.9 Demo 中默认启用，已使用本地规则 fallback。")
    return local


def save_qa_log(result: dict[str, Any], data_dir: str | Path = "data") -> tuple[str, str]:
    directory = Path(data_dir) / "qa_logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = directory / f"qa_{stamp}.json"
    markdown_path = directory / f"qa_{stamp}.md"
    counter = 1
    while json_path.exists() or markdown_path.exists():
        json_path = directory / f"qa_{stamp}_{counter}.json"
        markdown_path = directory / f"qa_{stamp}_{counter}.md"
        counter += 1
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_qa_markdown(result), encoding="utf-8")
    return json_path.as_posix(), markdown_path.as_posix()


def render_qa_markdown(result: dict[str, Any]) -> str:
    sources = "\n".join(
        f"- {item.get('path', '')}: {item.get('label', '')}"
        for item in result.get("sources", [])
    ) or "- 无"
    warnings = "\n".join(f"- {item}" for item in result.get("warnings", [])) or "- 无"
    return f"""# Story OS 问答记录

## 问题

{result.get("question", "")}

## 回答

{result.get("answer", "")}

## 置信度

{result.get("confidence", "")}

## 来源

{sources}

## Warnings

{warnings}
"""


def format_qa_text(result: dict[str, Any]) -> str:
    sources = result.get("sources", [])
    lines = [
        f"问题：{result.get('question', '')}",
        "",
        "回答：",
        str(result.get("answer", "")),
        "",
        f"置信度：{result.get('confidence', '')}",
        "",
        "来源：",
    ]
    if sources:
        lines.extend(f"- {item.get('path', '')}: {item.get('label', '')}" for item in sources)
    else:
        lines.append("- 无")
    warnings = result.get("warnings", [])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"


def _current_chapter_fact(sources: dict[str, Any]) -> dict[str, Any]:
    state = sources.get("state", {})
    current = int(state.get("current_chapter", 0) or 0) if isinstance(state, dict) else 0
    return _fact(
        f"当前已提交到第 {current} 章，下一章是第 {current + 1} 章。",
        "high",
        "state",
        "data/state.json",
        "state.current_chapter",
        str(current),
        related={"chapters": [current] if current else []},
    )


def _foreshadow_fact(sources: dict[str, Any]) -> dict[str, Any] | None:
    state = sources.get("state", {})
    foreshadows = state.get("foreshadows", []) if isinstance(state, dict) else []
    if not isinstance(foreshadows, list):
        plot = state.get("plot", {}) if isinstance(state, dict) else {}
        foreshadows = plot.get("foreshadows", []) if isinstance(plot, dict) else []
    open_items = [
        item for item in foreshadows
        if isinstance(item, dict) and item.get("status") in {"open", "planned"}
    ]
    if not open_items:
        return None
    lines = [f"当前共有 {len(open_items)} 个 open/planned 伏笔："]
    for index, item in enumerate(open_items, 1):
        lines.append(f"{index}. {item.get('content', '')}（状态：{item.get('status', '')}）")
    return _fact(
        "\n".join(lines),
        "high",
        "state",
        "data/state.json",
        "state.foreshadows",
        json.dumps(open_items, ensure_ascii=False),
        related={"foreshadows": [item.get("id") for item in open_items if item.get("id")]},
    )


def _character_fact(question: str, sources: dict[str, Any]) -> dict[str, Any] | None:
    state = sources.get("state", {})
    characters_data = sources.get("characters", {})
    state_characters = state.get("characters", {}) if isinstance(state, dict) else {}
    for name, value in state_characters.items() if isinstance(state_characters, dict) else []:
        if str(name).lower() in question:
            return _fact(
                f"{name} 当前状态：{json.dumps(value, ensure_ascii=False)}",
                "high",
                "state",
                "data/state.json",
                f"state.characters.{name}",
                json.dumps(value, ensure_ascii=False),
                related={"characters": [name]},
            )
    for character in _all_characters(characters_data):
        name = str(character.get("name") or character.get("id") or "")
        if name and name.lower() in question:
            parts = [
                f"{name} 的基础设定：",
                f"- 角色定位：{character.get('role', '')}",
                f"- 当前状态：{json.dumps(character.get('current_state', {}), ensure_ascii=False)}",
                f"- 关系：{json.dumps(character.get('relationships', {}), ensure_ascii=False)}",
                f"- 声音：{json.dumps(character.get('voice_profile', {}), ensure_ascii=False)}",
            ]
            return _fact(
                "\n".join(parts),
                "medium",
                "characters",
                "data/characters.json",
                f"characters.{name}",
                json.dumps(character, ensure_ascii=False),
                related={"characters": [name]},
            )
    return None


def _world_rule_fact(sources: dict[str, Any]) -> dict[str, Any] | None:
    world = sources.get("world_bible", {})
    state = sources.get("state", {})
    rules: list[str] = []
    if isinstance(world, dict):
        for key in ["core_rules", "continuity_rules", "power_or_system"]:
            value = world.get(key, [])
            rules.extend(_stringify_rule_items(value))
    if isinstance(state, dict):
        rules.extend(_stringify_rule_items(state.get("world", {}).get("rules", [])) if isinstance(state.get("world"), dict) else [])
    if not rules:
        return None
    return _fact(
        "当前世界观/设定规则：\n" + "\n".join(f"- {item}" for item in rules),
        "high",
        "world",
        "data/world_bible.json",
        "world_bible.rules",
        "\n".join(rules),
    )


def _todo_fact(sources: dict[str, Any]) -> dict[str, Any] | None:
    todos = sources.get("todos", {})
    items = todos.get("items", []) if isinstance(todos, dict) else []
    active = [
        item for item in items
        if isinstance(item, dict) and item.get("status") in {"open", "in_progress"} and item.get("priority") in {"urgent", "high", "medium"}
    ]
    if not active:
        return None
    lines = [f"当前有 {len(active)} 个活跃待办："]
    for item in active[:10]:
        chapter = f"[第{item.get('chapter_id')}章]" if item.get("chapter_id") else ""
        lines.append(f"- #{item.get('id')} [{item.get('priority')}][{item.get('type')}]{chapter} {item.get('title')}")
    return _fact(
        "\n".join(lines),
        "high",
        "todos",
        "data/todos/todos.json",
        "todos.items",
        json.dumps(active[:10], ensure_ascii=False),
        related={"todos": [item.get("id") for item in active if item.get("id")]},
    )


def _quality_fact(question: str, sources: dict[str, Any]) -> dict[str, Any] | None:
    root = Path(sources.get("_meta", {}).get("data_dir", "data"))
    reports = sorted((root / "quality_reports").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return None
    report = _read_json(reports[0])
    flags = report.get("flags", [])
    score = report.get("overall_score")
    lines = [f"最新质量报告评分：{score}", "主要问题："]
    lines.extend(f"- [{item.get('severity', '')}] {item.get('type', '')}: {item.get('message', '')}" for item in flags[:5] if isinstance(item, dict))
    return _fact(
        "\n".join(lines),
        "high" if "评分" in question or "质量" in question else "medium",
        "quality",
        reports[0].as_posix(),
        "quality_report.latest",
        json.dumps(report, ensure_ascii=False)[:500],
        related={"quality_reports": [reports[0].as_posix()]},
    )


def _score_summary(data: dict[str, Any], path: Path, keywords: list[str], question: str) -> dict[str, Any] | None:
    field_map = {
        "short_summary": data.get("short_summary", ""),
        "key_events": data.get("key_events", []),
        "memory_tags": data.get("memory_tags", []),
        "chapter_title": data.get("chapter_title", data.get("title", "")),
    }
    return _score_text_fields(field_map, path, int(data.get("chapter_id", 0) or 0), keywords, question)


def _score_memory_index_entry(chapter: dict[str, Any], root: Path, keywords: list[str], question: str) -> dict[str, Any] | None:
    path = Path(str(chapter.get("summary_path", "")))
    if not path.is_absolute():
        path = root.parent / path
    field_map = {
        "short_summary": chapter.get("short_summary", chapter.get("summary", "")),
        "key_events": chapter.get("key_events", []),
        "memory_tags": chapter.get("memory_tags", []),
        "chapter_title": chapter.get("chapter_title", chapter.get("title", "")),
    }
    return _score_text_fields(field_map, path, int(chapter.get("chapter_id", 0) or 0), keywords, question)


def _score_text_fields(
    field_map: dict[str, Any],
    path: Path,
    chapter_id: int,
    keywords: list[str],
    question: str,
) -> dict[str, Any] | None:
    matched: list[str] = []
    snippets: list[str] = []
    score = 0.0
    for field, value in field_map.items():
        text = _flatten_text(value)
        if not text:
            continue
        hits = sum(1 for keyword in keywords if keyword and keyword in text.lower())
        if question in text.lower():
            hits += 3
        if hits:
            matched.append(field)
            snippets.append(text[:180])
            score += min(0.2 + hits * 0.15, 0.8)
    if not matched:
        return None
    return {
        "type": "summary",
        "chapter_id": chapter_id,
        "path": path.as_posix(),
        "score": min(score, 1.0),
        "snippet": snippets[0],
        "matched_fields": matched,
    }


def _qa_result(
    question: str,
    answer: str,
    mode: str,
    confidence: str,
    sources: list[dict[str, Any]],
    related: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "qa_version": QA_VERSION,
        "question": question,
        "answer": answer,
        "mode": mode,
        "confidence": confidence,
        "sources": _dedupe_sources(sources),
        "related": _normalize_related(related),
        "warnings": warnings or [],
    }


def _fact(
    answer: str,
    confidence: str,
    source_type: str,
    path: str,
    label: str,
    snippet: str,
    related: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "confidence": confidence,
        "sources": [{"type": source_type, "path": path, "label": label, "snippet": snippet}],
        "related": _normalize_related(related),
    }


def _source_from_search(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(item.get("type", "summary")),
        "path": str(item.get("path", "")),
        "label": ",".join(str(field) for field in item.get("matched_fields", [])),
        "snippet": str(item.get("snippet", "")),
    }


def _best_confidence(items: list[dict[str, Any]]) -> str:
    if not items:
        return "unknown"
    return sorted((str(item.get("confidence", "unknown")) for item in items), key=lambda value: CONFIDENCE_ORDER.get(value, 9))[0]


def _merge_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _dedupe_sources([source for item in items for source in item.get("sources", [])])


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for source in sources:
        key = (str(source.get("type", "")), str(source.get("path", "")), str(source.get("label", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _merge_related(items: list[dict[str, Any]]) -> dict[str, Any]:
    merged = _normalize_related(None)
    for item in items:
        related = item.get("related", {})
        for key in merged:
            values = related.get(key, []) if isinstance(related, dict) else []
            for value in values:
                if value not in merged[key]:
                    merged[key].append(value)
    return merged


def _normalize_related(related: dict[str, Any] | None) -> dict[str, Any]:
    base = {
        "chapters": [],
        "characters": [],
        "foreshadows": [],
        "todos": [],
        "quality_reports": [],
    }
    if not related:
        return base
    for key in base:
        values = related.get(key, [])
        if not isinstance(values, list):
            values = [values]
        base[key] = [value for value in values if value not in {"", None}]
    return base


def _matches(question: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in question for keyword in keywords)


def _keywords(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]{2,}", question.lower())
    extra = [question[i:i + 2] for i in range(max(len(question) - 1, 0)) if "\u4e00" <= question[i] <= "\u9fff"]
    return list(dict.fromkeys(words + extra))


def _flatten_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _all_characters(characters_data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(characters_data, dict):
        return result
    for key in ["main_characters", "supporting_characters"]:
        value = characters_data.get(key, [])
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, dict))
    return result


def _stringify_rule_items(value: Any) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(str(item.get("rule") or item.get("name") or item.get("content") or item))
            else:
                result.append(str(item))
        return [item for item in result if item]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)]
    if value:
        return [str(value)]
    return []
