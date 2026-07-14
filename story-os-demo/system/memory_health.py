from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Keep the established report contract; additive checks do not require a
# breaking schema-version bump.
HEALTH_VERSION = "2.4-A"
VALID_LEVELS = {"error", "warning", "info"}
VALID_CATEGORIES = {"project", "state", "chapter", "summary", "version", "quality", "todo", "vector"}
VALID_SOURCE_TYPES = {"draft", "edited", "manual"}
CHAPTER_FILE_RE = re.compile(r"^chapter_(\d{3})\.md$")
VERSION_INDEX_RE = re.compile(r"^chapter_(\d{3})_versions\.json$")


def run_memory_health_check(data_dir: str | Path = "data", full: bool = False) -> dict[str, Any]:
    root = Path(data_dir)
    sections = {
        "project_initialization": check_project_initialization(root),
        "state_consistency": check_state_consistency(root),
        "chapter_files": check_chapter_files(root),
        "summary_files": check_summary_files(root),
        "version_integrity": check_version_integrity(root),
        "quality_reports": check_quality_reports(root),
        "todos": check_todos(root),
        "vector_index": check_vector_index(root),
    }
    issues = _collect_issues(sections)
    summary = {
        "errors": sum(1 for issue in issues if issue.get("level") == "error"),
        "warnings": sum(1 for issue in issues if issue.get("level") == "warning"),
        "infos": sum(1 for issue in issues if issue.get("level") == "info"),
    }
    total_checks = max(sum(int(section.get("checked", 0) or 0) for section in sections.values()), 1)
    weighted = summary["errors"] * 2 + summary["warnings"]
    return {
        "health_version": HEALTH_VERSION,
        "overall_status": _overall_status(summary),
        "overall_score": max(0.0, round(1.0 - (weighted / (total_checks * 2)), 2)),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "sections": sections if full else _compact_sections(sections),
        "issues": issues,
        "suggestions": _build_suggestions(issues),
    }


def check_project_initialization(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    story_spec_path = data_dir / "story_spec.json"
    state_path = data_dir / "state.json"
    project_path = data_dir / "project.md"
    if not story_spec_path.exists():
        issues.append(_issue("missing_story_spec", "error", "project", "缺少 data/story_spec.json。", story_spec_path, "请先创建小说项目。"))
    if not state_path.exists():
        issues.append(_issue("missing_state", "error", "state", "缺少 data/state.json。", state_path, "创建或恢复项目状态。"))
    if not project_path.exists():
        issues.append(_issue("missing_project_md", "warning", "project", "缺少 data/project.md。", project_path, "重新生成项目 Markdown 摘要。"))
    if state_path.exists():
        state, error = _read_json(state_path)
        if error:
            issues.append(_issue("invalid_state_json", "error", "state", "data/state.json 无法解析为 JSON。", state_path, "修复 state.json 语法。"))
        elif "current_chapter" not in state:
            issues.append(_issue("missing_current_chapter", "error", "state", "state.current_chapter 字段缺失。", state_path, "添加 current_chapter 整数字段。"))
        elif not isinstance(state.get("current_chapter"), int):
            issues.append(_issue("invalid_current_chapter", "error", "state", "state.current_chapter 必须是整数。", state_path, "将 current_chapter 设置为整数。"))
    return _section("project_initialization", issues, checked=5)


def check_state_consistency(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    state = _load_state(data_dir, issues)
    current_chapter = state.get("current_chapter") if isinstance(state, dict) else None
    chapter_count = len(_official_chapter_files(data_dir))
    if isinstance(current_chapter, int):
        if current_chapter > chapter_count:
            issues.append(_issue("state_ahead_of_chapters", "error", "state", "state.current_chapter 大于正式章节数量。", data_dir / "state.json", "检查章节文件是否缺失。", [data_dir / "chapters"]))
        if chapter_count > current_chapter:
            issues.append(_issue("chapters_ahead_of_state", "error", "chapter", "正式章节数量大于 state.current_chapter。", data_dir / "chapters", "检查 state.json 是否在提交后未更新。", [data_dir / "state.json"]))
    return _section("state_consistency", issues, checked=2, details={"current_chapter": current_chapter, "official_chapter_count": chapter_count})


def check_chapter_files(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    chapter_dir = data_dir / "chapters"
    if not chapter_dir.exists():
        issues.append(_issue("chapters_dir_missing", "info", "chapter", "data/chapters 目录还不存在。", chapter_dir, "提交第一章前无需操作。"))
        return _section("chapter_files", issues, checked=1)
    matched_ids: list[int] = []
    checked = 1
    for path in sorted(chapter_dir.glob("*.md")):
        checked += 1
        match = CHAPTER_FILE_RE.match(path.name)
        if not match:
            issues.append(_issue("invalid_chapter_filename", "error", "chapter", f"无效的正式章节文件名：{path.name}。", path, "将正式章节重命名为 chapter_001.md 格式。"))
            continue
        chapter_id = int(match.group(1))
        matched_ids.append(chapter_id)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(_issue("chapter_decode_failed", "error", "chapter", f"章节文件不是有效的 UTF-8 编码：{path.name}。", path, "将章节文件保存为 UTF-8 编码。"))
            continue
        if not text.strip():
            issues.append(_issue("empty_chapter_file", "error", "chapter", f"章节文件为空：{path.name}。", path, "恢复或删除空的正式章节。"))
        elif len(text.strip()) < 200:
            issues.append(_issue("short_chapter_file", "warning", "chapter", f"正式章节短于 200 字符：{path.name}。", path, "确认此已提交章节是完整的。"))
    for missing_id in _missing_numbers(matched_ids):
        issues.append(_issue("chapter_number_gap", "error", "chapter", f"缺少正式章节编号：chapter_{missing_id:03d}.md。", chapter_dir, "检查跳号或命名错误的章节文件。"))
    return _section("chapter_files", issues, checked=checked, details={"chapter_ids": matched_ids})


def check_summary_files(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checked = 0
    for chapter_path in _official_chapter_files(data_dir):
        checked += 1
        chapter_id = _chapter_id_from_path(chapter_path)
        summary_path = data_dir / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
        if not summary_path.exists():
            issues.append(_issue("missing_summary", "warning", "summary", f"缺少第 {chapter_id} 章摘要。", summary_path, "生成或恢复章节摘要。"))
            continue
        summary, error = _read_json(summary_path)
        if error:
            issues.append(_issue("invalid_summary_json", "error", "summary", f"摘要 JSON 无法解析：{summary_path.name}。", summary_path, "修复摘要 JSON 语法。"))
            continue
        if "chapter_id" not in summary:
            issues.append(_issue("summary_missing_chapter_id", "warning", "summary", f"摘要缺少 chapter_id：{summary_path.name}。", summary_path, "在摘要中添加 chapter_id。"))
        if "short_summary" not in summary and "summary" not in summary:
            issues.append(_issue("summary_missing_text", "warning", "summary", f"摘要缺少正文内容：{summary_path.name}。", summary_path, "添加摘要正文。"))
    return _section("summary_files", issues, checked=checked)


def check_version_integrity(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    versions_dir = data_dir / "versions"
    if not versions_dir.exists():
        issues.append(_issue("versions_dir_missing", "info", "version", "data/versions 目录还不存在。", versions_dir, "有草稿版本前无需操作。"))
        return _section("version_integrity", issues, checked=1)
    checked = 1
    for index_path in sorted(versions_dir.glob("chapter_*_versions.json")):
        checked += 1
        index, error = _read_json(index_path)
        if error:
            issues.append(_issue("invalid_version_index_json", "error", "version", f"版本索引 JSON 无法解析：{index_path.name}。", index_path, "修复版本索引 JSON 语法。"))
            continue
        selected = index.get("selected")
        if isinstance(selected, dict) and selected:
            _check_selected_version(selected, index_path, issues)
        for source_type, collection_key in [("draft", "drafts"), ("edited", "edited"), ("manual", "manual")]:
            items = index.get(collection_key, [])
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    _check_version_payload(source_type, item, issues)
    return _section("version_integrity", issues, checked=checked)


def check_quality_reports(data_dir: Path) -> dict[str, Any]:
    """Check reports against the current active canon, never a selected draft."""
    from core.project_context import get_project_context
    from system.memory_repair_service import MemoryRepairService
    root = data_dir.parent if data_dir.name == "data" else data_dir
    status = MemoryRepairService(get_project_context(root)).quality_status()
    issues: list[dict[str, Any]] = []
    if status["status"] in {"missing", "stale", "failed"}:
        issues.append(_issue("quality_report_current_version", "warning", "quality", status["message"], data_dir / "quality_reports", "生成当前正史版本的 Lite 质量报告。", impact="创作健康评分的数据完整度会降低。", recoverable=True, repair_action="generate_quality_report", details=status))
    elif status["status"] == "generating":
        issues.append(_issue("quality_report_generating", "info", "quality", status["message"], data_dir / "quality_reports", "等待当前任务完成后重新检查。", impact="质量健康数据暂时不完整。", recoverable=True, repair_action="generate_quality_report", details=status))
    for issue in issues:
        if issue.get("repair_action") == "generate_quality_report":
            issue["suggested_action"] = "\u751f\u6210\u5f53\u524d\u6b63\u53f2\u7248\u672c\u7684 Lite \u8d28\u91cf\u62a5\u544a\u3002"
            issue["impact"] = "\u521b\u4f5c\u5065\u5eb7\u8bc4\u5206\u7684\u6570\u636e\u5b8c\u6574\u5ea6\u4f1a\u964d\u4f4e\u3002"
    if status["status"] == "not_applicable":
        issues.append(_issue("quality_reports_not_applicable", "info", "quality", status["message"], data_dir / "quality_reports", "Wait for an active canon chapter before generating a quality report.", details=status))
    return _section("quality_reports", issues, checked=max(1, len(status.get("items", []))), details=status)

    issues: list[dict[str, Any]] = []
    checked = 0
    quality_dir = data_dir / "quality_reports"
    selected_versions = _selected_versions(data_dir)
    for selected in selected_versions:
        checked += 1
        chapter_id = int(selected.get("chapter_id", 0) or _chapter_id_from_version_path(Path(str(selected.get("index_path", "")))))
        source_type = str(selected.get("source_type", ""))
        version = int(selected.get("version", 0) or 0)
        report_path = quality_dir / f"chapter_{chapter_id:03d}_{source_type}_v{version:03d}_quality.json"
        if not report_path.exists():
            issues.append(_issue("missing_quality_report", "warning", "quality", f"缺少选中版本 {source_type}_v{version:03d} 的质量报告。", report_path, "对选中版本运行质量检查。"))
    if quality_dir.exists():
        for report_path in sorted(quality_dir.glob("*_quality.json")):
            checked += 1
            report, error = _read_json(report_path)
            if error:
                issues.append(_issue("invalid_quality_report_json", "error", "quality", f"质量报告 JSON 无法解析：{report_path.name}。", report_path, "修复质量报告 JSON 语法。"))
                continue
            if "overall_score" not in report:
                issues.append(_issue("quality_missing_overall_score", "warning", "quality", f"质量报告缺少 overall_score：{report_path.name}。", report_path, "重新生成或修复质量报告。"))
    elif not selected_versions:
        issues.append(_issue("quality_reports_missing", "info", "quality", "data/quality_reports 目录还不存在。", quality_dir, "运行质量检查前无需操作。"))
    return _section("quality_reports", issues, checked=max(checked, 1))


def check_todos(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    todos_path = data_dir / "todos" / "todos.json"
    if not todos_path.exists():
        issues.append(_issue("todos_missing", "info", "todo", "data/todos/todos.json 还不存在。", todos_path, "使用 Todos 前无需操作。"))
        return _section("todos", issues, checked=1)
    payload, error = _read_json(todos_path)
    if error:
        issues.append(_issue("invalid_todos_json", "error", "todo", "Todos JSON 无法解析。", todos_path, "修复 Todos JSON 语法。"))
        return _section("todos", issues, checked=1)
    todos = payload.get("todos", payload if isinstance(payload, list) else [])
    todos = todos if isinstance(todos, list) else []
    open_todos = [todo for todo in todos if isinstance(todo, dict) and str(todo.get("status", "open")) in {"open", "todo", "doing"}]
    high_todos = [todo for todo in open_todos if str(todo.get("priority", "")).lower() == "high"]
    if len(open_todos) > 20:
        issues.append(_issue("too_many_open_todos", "warning", "todo", f"未完成的 Todo 超过 20 条：{len(open_todos)}。", todos_path, "检查并关闭过期的 Todo。"))
    if len(high_todos) > 5:
        issues.append(_issue("too_many_high_priority_todos", "warning", "todo", f"高优先级未完成 Todo 超过 5 条：{len(high_todos)}。", todos_path, "重新调整高优先级 Todo。"))
    return _section("todos", issues, checked=len(todos) + 1, details={"open_todos": len(open_todos), "high_priority_open_todos": len(high_todos)})


def check_vector_index(data_dir: Path) -> dict[str, Any]:
    """Expose repairable vector states; an initialized empty index is healthy."""
    from core.project_context import get_project_context
    from system.memory_repair_service import MemoryRepairService
    root = data_dir.parent if data_dir.name == "data" else data_dir
    status = MemoryRepairService(get_project_context(root)).vector_status()
    issues: list[dict[str, Any]] = []
    if status["status"] in {"missing", "stale", "degraded", "failed"}:
        issues.append(_issue("vector_index", "warning", "vector", status["message"], data_dir / "vector_index" / "metadata.json", "初始化或增量更新当前项目的本地向量索引。", impact="历史语义检索将降级为摘要和关键词检索。", recoverable=True, repair_action="initialize_vector_index", details=status))
    elif status["status"] == "building":
        issues.append(_issue("vector_index_building", "info", "vector", status["message"], data_dir / "vector_index" / "metadata.json", "等待索引任务完成后重新检查。", impact="语义检索暂时不可用。", recoverable=True, repair_action="initialize_vector_index", details=status))
    elif status["status"] == "not_configured":
        issues.append(_issue("vector_index_not_configured", "info", "vector", status["message"], data_dir / "vector_index" / "metadata.json", "安装或配置本地向量索引依赖；基础写作不受影响。", impact="语义检索不可用。", recoverable=True, repair_action="initialize_vector_index", details=status))
    for issue in issues:
        if issue.get("repair_action") == "initialize_vector_index":
            issue["suggested_action"] = "\u521d\u59cb\u5316\u6216\u66f4\u65b0\u5f53\u524d\u9879\u76ee\u7684\u672c\u5730\u5411\u91cf\u7d22\u5f15\u3002"
            issue["impact"] = "\u5386\u53f2\u8bed\u4e49\u68c0\u7d22\u5c06\u964d\u7ea7\u4e3a\u6458\u8981\u548c\u5173\u952e\u8bcd\u68c0\u7d22\u3002"
    if status["status"] == "missing" and not (status.get("source_snapshot") or {}).get("current_canon_versions"):
        issues.append(_issue("memory_index_missing", "info", "vector", "data/memory/memory_index.json is not initialized.", data_dir / "memory" / "memory_index.json", "Initialize the vector index after content becomes available.", details=status))
    return _section("vector_index", issues, checked=1, details=status)

    issues: list[dict[str, Any]] = []
    index_path = data_dir / "memory" / "memory_index.json"
    chapter_count = len(_official_chapter_files(data_dir))
    report_path = data_dir / "memory" / "vector_index_report.json"

    if not index_path.exists():
        issues.append(_issue("memory_index_missing", "info", "vector", "data/memory/memory_index.json 还不存在。", index_path, "索引记忆前无需操作。"))
        return _section("vector_index", issues, checked=1, details={"official_chapter_count": chapter_count, "indexed_chapter_count": 0})

    payload, error = _read_json(index_path)
    if error:
        issues.append(_issue("invalid_memory_index_json", "error", "vector", "memory_index JSON 无法解析。", index_path, "修复 memory_index JSON 语法。"))
        return _section("vector_index", issues, checked=1)

    indexed_count = _memory_index_chapter_count(payload)
    if indexed_count < chapter_count:
        issues.append(_issue("memory_index_behind_chapters", "warning", "vector", "memory_index 覆盖的章节少于正式章节文件。", index_path, "准备好后运行 index-vault。", [data_dir / "chapters"]))

    chroma_stats: dict[str, Any] = {}
    try:
        from system.vector_memory import is_available, collection_stats

        if is_available(data_dir):
            chroma_stats = collection_stats(data_dir)
            vc = chroma_stats.get("chapters_indexed", 0)
            if vc < chapter_count:
                issues.append(_issue(
                    "vector_index_behind_chapters", "warning", "vector",
                    f"ChromaDB 向量索引覆盖 {vc} 章，但正式章节有 {chapter_count} 章。",
                    report_path, "运行 index-vault 重建向量索引。",
                ))
        else:
            if chapter_count > 0:
                issues.append(_issue(
                    "vector_index_not_built", "info", "vector",
                    f"已有 {chapter_count} 章正文，但尚未构建 ChromaDB 向量索引。",
                    report_path, "点击'更新向量库'或运行 index-vault。",
                ))
    except Exception:
        pass

    return _section(
        "vector_index",
        issues,
        checked=2,
        details={
            "official_chapter_count": chapter_count,
            "indexed_chapter_count": indexed_count,
            "vector_chapters_indexed": chroma_stats.get("chapters_indexed", 0),
            "vector_chunks": chroma_stats.get("chunks_indexed", 0),
            "vector_indexed_at": chroma_stats.get("indexed_at", ""),
        },
    )


def render_memory_health_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    suggestions = report.get("suggestions", []) if isinstance(report.get("suggestions"), list) else []
    issue_lines = [
        f"- [{issue.get('level', '')}] {issue.get('id', '')}: {issue.get('message', '')} ({issue.get('path', '')})"
        for issue in issues
        if isinstance(issue, dict)
    ]
    suggestion_lines = [f"- {item}" for item in suggestions]
    return "\n".join([
        "# Story OS Memory Health Report",
        "",
        f"- 检查时间：{report.get('checked_at', '')}",
        f"- 总体状态：{report.get('overall_status', '')}",
        f"- 健康分：{report.get('overall_score', 0)}",
        f"- 错误：{summary.get('errors', 0)}",
        f"- 警告：{summary.get('warnings', 0)}",
        f"- 信息：{summary.get('infos', 0)}",
        "",
        "## 问题列表",
        "",
        "\n".join(issue_lines) if issue_lines else "暂无问题。",
        "",
        "## 建议下一步",
        "",
        "\n".join(suggestion_lines) if suggestion_lines else "保持当前滚动式逐章工作流。",
        "",
    ])


def save_memory_health_report(report: dict[str, Any], data_dir: str | Path = "data") -> dict[str, str]:
    health_dir = Path(data_dir) / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    json_path = health_dir / "latest_memory_health.json"
    markdown_path = health_dir / "latest_memory_health.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_memory_health_markdown(report), encoding="utf-8")
    return {"json_path": json_path.as_posix(), "markdown_path": markdown_path.as_posix()}


def _issue(
    issue_id: str,
    level: str,
    category: str,
    message: str,
    path: str | Path,
    suggested_action: str,
    related_paths: list[str | Path] | None = None,
    *, impact: str = "", recoverable: bool = False, repair_action: str = "", details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "level": level if level in VALID_LEVELS else "info",
        "category": category if category in VALID_CATEGORIES else "project",
        "message": message,
        "path": Path(path).as_posix(),
        "suggested_action": suggested_action,
        "related_paths": [Path(item).as_posix() for item in (related_paths or [])],
        "impact": impact,
        "recoverable": recoverable,
        "repair_action": repair_action,
        "details": details or {},
    }


def _section(name: str, issues: list[dict[str, Any]], checked: int, details: dict[str, Any] | None = None) -> dict[str, Any]:
    errors = sum(1 for issue in issues if issue.get("level") == "error")
    warnings = sum(1 for issue in issues if issue.get("level") == "warning")
    infos = sum(1 for issue in issues if issue.get("level") == "info")
    return {
        "name": name,
        "status": _overall_status({"errors": errors, "warnings": warnings, "infos": infos}),
        "checked": checked,
        "summary": {"errors": errors, "warnings": warnings, "infos": infos},
        "issues": issues,
        "details": details or {},
    }


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, str(exc)
    return payload if isinstance(payload, dict) else {"items": payload}, ""


def _load_state(data_dir: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    state_path = data_dir / "state.json"
    if not state_path.exists():
        return {}
    state, error = _read_json(state_path)
    if error:
        issues.append(_issue("invalid_state_json", "error", "state", "data/state.json 无法解析为 JSON。", state_path, "修复 state.json 语法。"))
    return state


def _official_chapter_files(data_dir: Path) -> list[Path]:
    chapter_dir = data_dir / "chapters"
    if not chapter_dir.exists():
        return []
    return [path for path in sorted(chapter_dir.glob("chapter_*.md")) if CHAPTER_FILE_RE.match(path.name)]


def _chapter_id_from_path(path: Path) -> int:
    match = CHAPTER_FILE_RE.match(path.name)
    return int(match.group(1)) if match else 0


def _missing_numbers(values: list[int]) -> list[int]:
    if not values:
        return []
    present = set(values)
    return [item for item in range(1, max(values) + 1) if item not in present]


def _check_selected_version(selected: dict[str, Any], index_path: Path, issues: list[dict[str, Any]]) -> None:
    source_type = str(selected.get("source_type", ""))
    if source_type not in VALID_SOURCE_TYPES:
        issues.append(_issue("selected_invalid_source_type", "error", "version", "选中版本的 source_type 必须是 draft、edited 或 manual。", index_path, "选择有效的版本来源类型。"))
    json_path = Path(str(selected.get("json_path", "")))
    if not json_path.exists():
        issues.append(_issue("selected_version_missing", "error", "version", "选中版本的 json_path 指向的文件不存在。", json_path if str(json_path) else index_path, "选择现有版本或恢复缺失文件。", [index_path]))


def _check_version_payload(source_type: str, item: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    json_path = Path(str(item.get("json_path", "")))
    if not json_path.exists():
        return
    payload, error = _read_json(json_path)
    if error:
        issues.append(_issue("invalid_version_payload_json", "error", "version", f"版本文件 JSON 无法解析：{json_path.name}。", json_path, "修复版本文件 JSON 语法。"))
        return
    required_text_key = {"draft": "draft_text", "edited": "edited_text", "manual": "manual_text"}[source_type]
    if required_text_key not in payload:
        issues.append(_issue(f"{source_type}_missing_text", "warning", "version", f"版本缺少 {required_text_key} 字段：{json_path.name}。", json_path, f"添加 {required_text_key} 或重新生成版本。"))


def _selected_versions(data_dir: Path) -> list[dict[str, Any]]:
    versions_dir = data_dir / "versions"
    result: list[dict[str, Any]] = []
    if not versions_dir.exists():
        return result
    for index_path in sorted(versions_dir.glob("chapter_*_versions.json")):
        index, error = _read_json(index_path)
        if error:
            continue
        selected = index.get("selected")
        if isinstance(selected, dict) and selected:
            item = dict(selected)
            item["chapter_id"] = index.get("chapter_id", _chapter_id_from_version_path(index_path))
            item["index_path"] = index_path.as_posix()
            result.append(item)
    return result


def _chapter_id_from_version_path(path: Path) -> int:
    match = VERSION_INDEX_RE.match(path.name)
    return int(match.group(1)) if match else 0


def _memory_index_chapter_count(payload: dict[str, Any]) -> int:
    for key in ["chapters", "indexed_chapters", "chapter_ids"]:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    entries = payload.get("entries")
    if isinstance(entries, list):
        ids = {item.get("chapter_id") for item in entries if isinstance(item, dict) and item.get("chapter_id")}
        return len(ids) if ids else len(entries)
    return int(payload.get("chapter_count", 0) or 0)


def _collect_issues(sections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for section in sections.values():
        section_issues = section.get("issues", [])
        if isinstance(section_issues, list):
            issues.extend(issue for issue in section_issues if isinstance(issue, dict))
    return issues


def _compact_sections(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, section in sections.items():
        compact[key] = {
            "status": section.get("status", "ok"),
            "checked": section.get("checked", 0),
            "summary": section.get("summary", {}),
            "details": section.get("details", {}),
        }
    return compact


def _overall_status(summary: dict[str, int]) -> str:
    if int(summary.get("errors", 0) or 0) > 0:
        return "error"
    if int(summary.get("warnings", 0) or 0) > 0:
        return "warning"
    return "ok"


def _build_suggestions(issues: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    for issue in issues:
        action = str(issue.get("suggested_action", "")).strip()
        if action and action not in suggestions:
            suggestions.append(action)
    return suggestions[:10]
