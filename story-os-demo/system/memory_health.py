from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

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
        issues.append(_issue("missing_story_spec", "error", "project", "Missing data/story_spec.json.", story_spec_path, "Create the story project first."))
    if not state_path.exists():
        issues.append(_issue("missing_state", "error", "state", "Missing data/state.json.", state_path, "Create or restore project state."))
    if not project_path.exists():
        issues.append(_issue("missing_project_md", "warning", "project", "Missing data/project.md.", project_path, "Regenerate the project markdown summary."))
    if state_path.exists():
        state, error = _read_json(state_path)
        if error:
            issues.append(_issue("invalid_state_json", "error", "state", "data/state.json cannot be parsed as JSON.", state_path, "Repair state.json syntax."))
        elif "current_chapter" not in state:
            issues.append(_issue("missing_current_chapter", "error", "state", "state.current_chapter is missing.", state_path, "Add current_chapter as an integer."))
        elif not isinstance(state.get("current_chapter"), int):
            issues.append(_issue("invalid_current_chapter", "error", "state", "state.current_chapter must be an integer.", state_path, "Set current_chapter to an integer."))
    return _section("project_initialization", issues, checked=5)


def check_state_consistency(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    state = _load_state(data_dir, issues)
    current_chapter = state.get("current_chapter") if isinstance(state, dict) else None
    chapter_count = len(_official_chapter_files(data_dir))
    if isinstance(current_chapter, int):
        if current_chapter > chapter_count:
            issues.append(_issue("state_ahead_of_chapters", "error", "state", "state.current_chapter is greater than official chapter count.", data_dir / "state.json", "Check whether chapter files are missing.", [data_dir / "chapters"]))
        if chapter_count > current_chapter:
            issues.append(_issue("chapters_ahead_of_state", "error", "chapter", "Official chapter count is greater than state.current_chapter.", data_dir / "chapters", "Check whether state.json was not updated after commit.", [data_dir / "state.json"]))
    return _section("state_consistency", issues, checked=2, details={"current_chapter": current_chapter, "official_chapter_count": chapter_count})


def check_chapter_files(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    chapter_dir = data_dir / "chapters"
    if not chapter_dir.exists():
        issues.append(_issue("chapters_dir_missing", "info", "chapter", "data/chapters does not exist yet.", chapter_dir, "No action needed before the first committed chapter."))
        return _section("chapter_files", issues, checked=1)
    matched_ids: list[int] = []
    checked = 1
    for path in sorted(chapter_dir.glob("*.md")):
        checked += 1
        match = CHAPTER_FILE_RE.match(path.name)
        if not match:
            issues.append(_issue("invalid_chapter_filename", "error", "chapter", f"Invalid official chapter filename: {path.name}.", path, "Rename official chapters as chapter_001.md."))
            continue
        chapter_id = int(match.group(1))
        matched_ids.append(chapter_id)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(_issue("chapter_decode_failed", "error", "chapter", f"Chapter file is not valid UTF-8: {path.name}.", path, "Save the chapter file as UTF-8."))
            continue
        if not text.strip():
            issues.append(_issue("empty_chapter_file", "error", "chapter", f"Chapter file is empty: {path.name}.", path, "Restore or remove the empty official chapter."))
        elif len(text.strip()) < 200:
            issues.append(_issue("short_chapter_file", "warning", "chapter", f"Official chapter is shorter than 200 characters: {path.name}.", path, "Confirm this committed chapter is complete."))
    for missing_id in _missing_numbers(matched_ids):
        issues.append(_issue("chapter_number_gap", "error", "chapter", f"Missing official chapter number: chapter_{missing_id:03d}.md.", chapter_dir, "Check for skipped or misnamed chapter files."))
    return _section("chapter_files", issues, checked=checked, details={"chapter_ids": matched_ids})


def check_summary_files(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checked = 0
    for chapter_path in _official_chapter_files(data_dir):
        checked += 1
        chapter_id = _chapter_id_from_path(chapter_path)
        summary_path = data_dir / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
        if not summary_path.exists():
            issues.append(_issue("missing_summary", "warning", "summary", f"Missing summary for chapter_{chapter_id:03d}.", summary_path, "Generate or restore the chapter summary."))
            continue
        summary, error = _read_json(summary_path)
        if error:
            issues.append(_issue("invalid_summary_json", "error", "summary", f"Summary JSON cannot be parsed: {summary_path.name}.", summary_path, "Repair summary JSON syntax."))
            continue
        if "chapter_id" not in summary:
            issues.append(_issue("summary_missing_chapter_id", "warning", "summary", f"Summary is missing chapter_id: {summary_path.name}.", summary_path, "Add chapter_id to the summary."))
        if "summary" not in summary:
            issues.append(_issue("summary_missing_text", "warning", "summary", f"Summary is missing summary text: {summary_path.name}.", summary_path, "Add summary text."))
    return _section("summary_files", issues, checked=checked)


def check_version_integrity(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    versions_dir = data_dir / "versions"
    if not versions_dir.exists():
        issues.append(_issue("versions_dir_missing", "info", "version", "data/versions does not exist yet.", versions_dir, "No action needed before draft versions exist."))
        return _section("version_integrity", issues, checked=1)
    checked = 1
    for index_path in sorted(versions_dir.glob("chapter_*_versions.json")):
        checked += 1
        index, error = _read_json(index_path)
        if error:
            issues.append(_issue("invalid_version_index_json", "error", "version", f"Version index JSON cannot be parsed: {index_path.name}.", index_path, "Repair version index JSON syntax."))
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
            issues.append(_issue("missing_quality_report", "warning", "quality", f"Missing quality report for selected {source_type}_v{version:03d}.", report_path, "Run quality-check for the selected version."))
    if quality_dir.exists():
        for report_path in sorted(quality_dir.glob("*_quality.json")):
            checked += 1
            report, error = _read_json(report_path)
            if error:
                issues.append(_issue("invalid_quality_report_json", "error", "quality", f"Quality report JSON cannot be parsed: {report_path.name}.", report_path, "Repair quality report JSON syntax."))
                continue
            if "overall_score" not in report:
                issues.append(_issue("quality_missing_overall_score", "warning", "quality", f"Quality report is missing overall_score: {report_path.name}.", report_path, "Regenerate or repair the quality report."))
    elif not selected_versions:
        issues.append(_issue("quality_reports_missing", "info", "quality", "data/quality_reports does not exist yet.", quality_dir, "No action needed before quality-check."))
    return _section("quality_reports", issues, checked=max(checked, 1))


def check_todos(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    todos_path = data_dir / "todos" / "todos.json"
    if not todos_path.exists():
        issues.append(_issue("todos_missing", "info", "todo", "data/todos/todos.json does not exist yet.", todos_path, "No action needed until todos are used."))
        return _section("todos", issues, checked=1)
    payload, error = _read_json(todos_path)
    if error:
        issues.append(_issue("invalid_todos_json", "error", "todo", "Todos JSON cannot be parsed.", todos_path, "Repair todos JSON syntax."))
        return _section("todos", issues, checked=1)
    todos = payload.get("todos", payload if isinstance(payload, list) else [])
    todos = todos if isinstance(todos, list) else []
    open_todos = [todo for todo in todos if isinstance(todo, dict) and str(todo.get("status", "open")) in {"open", "todo", "doing"}]
    high_todos = [todo for todo in open_todos if str(todo.get("priority", "")).lower() == "high"]
    if len(open_todos) > 20:
        issues.append(_issue("too_many_open_todos", "warning", "todo", f"Open todos exceed 20: {len(open_todos)}.", todos_path, "Review and close stale todos."))
    if len(high_todos) > 5:
        issues.append(_issue("too_many_high_priority_todos", "warning", "todo", f"High priority open todos exceed 5: {len(high_todos)}.", todos_path, "Reprioritize high priority todos."))
    return _section("todos", issues, checked=len(todos) + 1, details={"open_todos": len(open_todos), "high_priority_open_todos": len(high_todos)})


def check_vector_index(data_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    index_path = data_dir / "memory" / "memory_index.json"
    chapter_count = len(_official_chapter_files(data_dir))
    if not index_path.exists():
        issues.append(_issue("memory_index_missing", "info", "vector", "data/memory/memory_index.json does not exist yet.", index_path, "No action needed before indexing memory."))
        return _section("vector_index", issues, checked=1, details={"official_chapter_count": chapter_count, "indexed_chapter_count": 0})
    payload, error = _read_json(index_path)
    if error:
        issues.append(_issue("invalid_memory_index_json", "error", "vector", "memory_index JSON cannot be parsed.", index_path, "Repair memory_index JSON syntax."))
        return _section("vector_index", issues, checked=1)
    indexed_count = _memory_index_chapter_count(payload)
    if indexed_count < chapter_count:
        issues.append(_issue("memory_index_behind_chapters", "warning", "vector", "memory_index covers fewer chapters than official chapter files.", index_path, "Run index-vault when ready.", [data_dir / "chapters"]))
    return _section("vector_index", issues, checked=1, details={"official_chapter_count": chapter_count, "indexed_chapter_count": indexed_count})


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
        f"- Errors：{summary.get('errors', 0)}",
        f"- Warnings：{summary.get('warnings', 0)}",
        f"- Infos：{summary.get('infos', 0)}",
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
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "level": level if level in VALID_LEVELS else "info",
        "category": category if category in VALID_CATEGORIES else "project",
        "message": message,
        "path": Path(path).as_posix(),
        "suggested_action": suggested_action,
        "related_paths": [Path(item).as_posix() for item in (related_paths or [])],
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
        issues.append(_issue("invalid_state_json", "error", "state", "data/state.json cannot be parsed as JSON.", state_path, "Repair state.json syntax."))
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
        issues.append(_issue("selected_invalid_source_type", "error", "version", "Selected version source_type must be draft, edited, or manual.", index_path, "Select a valid version source type."))
    json_path = Path(str(selected.get("json_path", "")))
    if not json_path.exists():
        issues.append(_issue("selected_version_missing", "error", "version", "Selected version json_path does not exist.", json_path if str(json_path) else index_path, "Select an existing version or restore the missing file.", [index_path]))


def _check_version_payload(source_type: str, item: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    json_path = Path(str(item.get("json_path", "")))
    if not json_path.exists():
        return
    payload, error = _read_json(json_path)
    if error:
        issues.append(_issue("invalid_version_payload_json", "error", "version", f"Version payload JSON cannot be parsed: {json_path.name}.", json_path, "Repair version payload JSON syntax."))
        return
    required_text_key = {"draft": "draft_text", "edited": "edited_text", "manual": "manual_text"}[source_type]
    if required_text_key not in payload:
        issues.append(_issue(f"{source_type}_missing_text", "warning", "version", f"{source_type} version is missing {required_text_key}: {json_path.name}.", json_path, f"Add {required_text_key} or regenerate the version."))


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
