from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.chapter_archive import active_chapter_entries
from system.quality_checker import load_quality_report, quality_report_paths
from system.version_manager import list_versions
from system.todo_manager import format_todo_for_cli, summarize_todos


DASHBOARD_VERSION = "2.0"
LOAD_WARNINGS: list[str] = []


def load_json_if_exists(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOAD_WARNINGS.append(f"Invalid JSON skipped: {target.as_posix()}")
        return default
    except (PermissionError, FileNotFoundError, OSError) as exc:
        LOAD_WARNINGS.append(f"Unreadable JSON skipped: {target.as_posix()} ({exc.__class__.__name__})")
        return default


def collect_project_info(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    spec = load_json_if_exists(root / "story_spec.json", {}) or {}
    blueprint = load_json_if_exists(root / "story_blueprint.json", {}) or {}
    return {
        "title": str(spec.get("title") or blueprint.get("title") or ""),
        "genre": str(spec.get("genre") or blueprint.get("genre") or ""),
        "length_type": str(spec.get("length_type") or blueprint.get("length_type") or ""),
        "target_word_count": int(spec.get("target_word_count", blueprint.get("target_word_count", 0)) or 0),
    }


def collect_progress_info(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    state = load_json_if_exists(root / "state.json", {}) or {}
    current_chapter = int(state.get("current_chapter", 0) or 0)
    active_chapters = active_chapter_entries(root)
    return {
        "current_chapter": current_chapter,
        "next_chapter": current_chapter + 1,
        "current_stage": str(state.get("current_stage", "")),
        "committed_chapters_count": len(active_chapters),
        "estimated_total_chapters": None,
        "active_chapters": active_chapters,
    }


def collect_next_chapter_state(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    plan = load_json_if_exists(root / "next_chapter_plan.json", {}) or {}
    chapter_id = _current_target_chapter(root)
    versions = list_versions(chapter_id, root)
    selected = versions.get("selected") if isinstance(versions.get("selected"), dict) and versions.get("selected") else None
    review = load_json_if_exists(root / "reviews" / f"chapter_{chapter_id:03d}_review.json", {}) or {}
    quality = collect_quality_status(root)
    return {
        "plan_exists": bool(plan),
        "draft_versions_count": len(versions.get("drafts", [])),
        "edited_versions_count": len(versions.get("edited", [])),
        "manual_versions_count": len(versions.get("manual", [])),
        "selected_version": selected,
        "review_status": str(review.get("status", "")),
        "quality_score": quality.get("latest_score"),
        "quality_report_exists": bool(quality.get("latest_report_path")),
    }


def collect_memory_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    state = load_json_if_exists(root / "state.json", {}) or {}
    vector_report = root / "memory" / "vector_index_report.json"
    vector_available = False
    vector_stats: dict[str, Any] = {}
    report_stats: dict[str, Any] = load_json_if_exists(vector_report, {}) or {}
    try:
        from system.vector_memory import is_available, collection_stats

        vector_available = bool(is_available(data_dir))
        vector_stats = collection_stats(data_dir) or {}
    except Exception:
        pass
    if not vector_stats.get("chapters_indexed") and report_stats.get("chapters_indexed") is not None:
        vector_stats = {
            **report_stats,
            **vector_stats,
        }
    return {
        "context_exists": (root / "context" / "current_context.json").exists(),
        "obsidian_synced": bool(state.get("obsidian", {}).get("synced")) if isinstance(state.get("obsidian"), dict) else False,
        "vector_memory_enabled": vector_available or vector_report.exists(),
        "vector_indexed_chapters": int(vector_stats.get("chapters_indexed", 0) or 0),
        "vector_chunks": int(vector_stats.get("chunks_indexed", 0) or 0),
        "last_vector_index_report": vector_report.as_posix() if vector_report.exists() else "",
        "memory_index_exists": (root / "memory" / "memory_index.json").exists(),
    }


def load_latest_memory_health_summary(data_dir: str | Path = "data") -> dict[str, Any]:
    path = Path(data_dir) / "health" / "latest_memory_health.json"
    if not path.exists():
        return {"exists": False}
    report = load_json_if_exists(path, {}) or {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    return {
        "exists": True,
        "overall_status": str(report.get("overall_status", "")),
        "overall_score": report.get("overall_score", 0),
        "errors": int(summary.get("errors", 0) or 0),
        "warnings": int(summary.get("warnings", 0) or 0),
        "infos": int(summary.get("infos", 0) or 0),
        "last_checked_at": str(report.get("checked_at", "")),
    }


def collect_quality_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    chapter_id = _current_target_chapter(root)
    source = _quality_source_for_chapter(chapter_id, root)
    if not source:
        return {"latest_score": None, "latest_report_path": "", "risk_level": "unknown", "main_flags": []}
    report = load_quality_report(chapter_id, source["source_type"], int(source["version"]), root)
    if not report:
        return {"latest_score": None, "latest_report_path": "", "risk_level": "unknown", "main_flags": []}
    score = report.get("overall_score")
    report_path = quality_report_paths(chapter_id, source["source_type"], int(source["version"]), root)[1]
    return {
        "latest_score": score,
        "latest_report_path": report_path.as_posix(),
        "risk_level": _risk_level(score),
        "main_flags": report.get("flags", [])[:5],
    }


def collect_foreshadow_status(data_dir: str | Path = "data") -> dict[str, Any]:
    state = load_json_if_exists(Path(data_dir) / "state.json", {}) or {}
    foreshadows = state.get("foreshadows", [])
    if not isinstance(foreshadows, list):
        plot = state.get("plot", {})
        foreshadows = plot.get("foreshadows", []) if isinstance(plot, dict) else []
    open_items = [item for item in foreshadows if isinstance(item, dict) and item.get("status") == "open"]
    return {
        "open_count": _count_status(foreshadows, "open"),
        "planned_count": _count_status(foreshadows, "planned"),
        "resolved_count": _count_status(foreshadows, "resolved"),
        "open_items": open_items[:10],
    }


def collect_version_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    chapter_id = _current_target_chapter(root)
    versions = list_versions(chapter_id, root)
    selected = versions.get("selected") if isinstance(versions.get("selected"), dict) and versions.get("selected") else None
    if selected is None:
        manual_versions = versions.get("manual", [])
        edited_versions = versions.get("edited", [])
        draft_versions = versions.get("drafts", [])
        if manual_versions:
            selected = manual_versions[-1]
        elif edited_versions:
            selected = edited_versions[-1]
        elif draft_versions:
            selected = draft_versions[-1]
    return {
        "drafts": versions.get("drafts", []),
        "edited": versions.get("edited", []),
        "manual": versions.get("manual", []),
        "selected": selected,
    }


def collect_todo_status(data_dir: str | Path = "data") -> dict[str, Any]:
    return summarize_todos(data_dir, current_chapter=_current_target_chapter(Path(data_dir)))


def collect_shell_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    logs = sorted((root / "shell_logs").glob("shell_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    return {
        "available": True,
        "last_shell_log": logs[0].as_posix() if logs else "",
        "aliases_enabled": True,
    }


def collect_qa_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    logs = sorted((root / "qa_logs").glob("qa_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return {
        "logs_count": len(logs),
        "latest_log_path": logs[0].as_posix() if logs else "",
        "ask_state_available": True,
        "ask_memory_available": True,
        "ask_story_available": True,
    }


def collect_health_status(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    missing_files: list[str] = []
    warnings: list[str] = list(LOAD_WARNINGS)
    errors: list[str] = []
    required = {
        "story_spec": root / "story_spec.json",
        "state": root / "state.json",
        "story_blueprint": root / "story_blueprint.json",
        "characters": root / "characters.json",
        "world_bible": root / "world_bible.json",
    }
    for key, path in required.items():
        if not path.exists():
            missing_files.append(path.as_posix())
            if key in {"story_spec", "state"}:
                errors.append(f"缺少关键文件：{path.as_posix()}")
            else:
                warnings.append(f"缺少可选阶段文件：{path.as_posix()}")
    state = load_json_if_exists(root / "state.json", {}) or {}
    stage = state.get("current_stage", "")
    if stage == "next_chapter_planned" and not (root / "next_chapter_plan.json").exists():
        warnings.append("current_stage 显示已规划下一章，但缺少 next_chapter_plan.json。")
    if stage == "waiting_for_review":
        chapter_id = _current_target_chapter(root)
        if not (root / "reviews" / f"chapter_{chapter_id:03d}_review.json").exists():
            warnings.append("current_stage 显示等待审核，但缺少 review record。")
    return {"missing_files": missing_files, "warnings": warnings, "errors": errors}


def suggest_next_actions(status: dict[str, Any]) -> list[dict[str, str]]:
    health = status.get("health", {})
    missing = set(health.get("missing_files", []))
    next_state = status.get("next_chapter_state", {})
    memory = status.get("memory", {})
    memory_health = status.get("memory_health", {})
    progress = status.get("progress", {})
    todos = status.get("todos", {})
    qa = status.get("qa", {})
    shell = status.get("shell", {})
    if any(path.endswith("story_spec.json") for path in missing):
        return [{"command": "python main.py setup", "reason": "尚未创建小说立项配置。"}]
    if any(path.endswith("story_blueprint.json") for path in missing):
        return [{"command": "python main.py blueprint", "reason": "已有小说设定，但尚未生成故事蓝图。"}]
    if any(path.endswith("characters.json") or path.endswith("world_bible.json") for path in missing):
        return [{"command": "python main.py build-assets", "reason": "尚未生成角色卡和世界观设定。"}]
    if int(todos.get("urgent_count", 0) or 0) > 0:
        return [{"command": "python main.py todo list --status open", "reason": "存在 urgent 待办，建议先处理最高优先级创作任务。"}]
    chapter_related = todos.get("chapter_related_open", [])
    if chapter_related:
        chapter = chapter_related[0].get("chapter_id", progress.get("next_chapter", ""))
        return [{"command": f"python main.py todo list --chapter {chapter}", "reason": "当前章节存在未处理的 revision/continuity 待办，建议先处理再审核。"}]
    if not next_state.get("plan_exists"):
        return [{"command": "python main.py plan-next", "reason": "下一章尚未规划。"}]
    if int(next_state.get("draft_versions_count", 0) or 0) == 0:
        return [{"command": "python main.py write-draft", "reason": "下一章已规划，但还没有草稿。"}]
    if int(next_state.get("edited_versions_count", 0) or 0) == 0:
        return [{"command": "python main.py edit-draft", "reason": "已有草稿，但还没有编辑版。"}]
    if not next_state.get("quality_report_exists"):
        return [{"command": "python main.py quality-check", "reason": "已有编辑版，建议先生成质量评估。"}]
    if next_state.get("review_status") == "pending" or progress.get("current_stage") == "waiting_for_review":
        return [{"command": "python main.py review-draft", "reason": "当前章节等待人工审核。"}]
    if next_state.get("review_status") == "rejected" or progress.get("current_stage") == "draft_rejected":
        return [{"command": "python main.py regenerate-draft", "reason": "当前草稿已被拒绝，建议重新生成。"}]
    if progress.get("current_stage") == "chapter_committed" and not memory.get("obsidian_synced"):
        return [{"command": "python main.py sync-obsidian", "reason": "章节已提交，但尚未同步到 Obsidian。"}]
    if memory.get("obsidian_synced") and not memory.get("vector_memory_enabled"):
        return [{"command": "python main.py index-vault", "reason": "Obsidian 已更新，建议重建向量索引。"}]
    return [{"command": "python main.py run-chapter", "reason": "当前状态正常，可以生成下一章。"}]


def build_status_dashboard(data_dir: str | Path = "data", full: bool = False) -> dict[str, Any]:
    LOAD_WARNINGS.clear()
    status = {
        "dashboard_version": DASHBOARD_VERSION,
        "project": collect_project_info(data_dir),
        "progress": collect_progress_info(data_dir),
        "next_chapter_state": collect_next_chapter_state(data_dir),
        "memory": collect_memory_status(data_dir),
        "memory_health": load_latest_memory_health_summary(data_dir),
        "quality": collect_quality_status(data_dir),
        "foreshadows": collect_foreshadow_status(data_dir),
        "todos": collect_todo_status(data_dir),
        "qa": collect_qa_status(data_dir),
        "shell": collect_shell_status(data_dir),
        "versions": collect_version_status(data_dir),
        "health": collect_health_status(data_dir),
        "next_actions": [],
    }
    if full:
        status["details"] = collect_full_details(data_dir)
    status["next_actions"] = suggest_next_actions(status)
    return status


def render_status_text(status: dict[str, Any], full: bool = False) -> str:
    project = status.get("project", {})
    progress = status.get("progress", {})
    next_state = status.get("next_chapter_state", {})
    memory = status.get("memory", {})
    memory_health = status.get("memory_health", {})
    quality = status.get("quality", {})
    foreshadows = status.get("foreshadows", {})
    todos = status.get("todos", {})
    qa = status.get("qa", {})
    shell = status.get("shell", {})
    selected = next_state.get("selected_version") or {}
    actions = status.get("next_actions", [])
    lines = [
        "Story OS 状态面板",
        "",
        "项目：",
        f"- 标题：{project.get('title', '')}",
        f"- 类型：{project.get('genre', '')}",
        f"- 篇幅：{project.get('length_type', '')}",
        f"- 目标字数：{project.get('target_word_count', 0)}",
        "",
        "进度：",
        f"- 当前已提交章节：第 {progress.get('current_chapter', 0)} 章",
        f"- 下一章：第 {progress.get('next_chapter', 1)} 章",
        f"- 当前阶段：{progress.get('current_stage', '')}",
        "",
        "下一章状态：",
        f"- 章节计划：{'已生成' if next_state.get('plan_exists') else '未生成'}",
        f"- 草稿版本：{next_state.get('draft_versions_count', 0)} 个",
        f"- 编辑版本：{next_state.get('edited_versions_count', 0)} 个",
        f"- 人工修改版本：{next_state.get('manual_versions_count', 0)} 个",
        f"- 当前选中版本：{_version_label(selected) if selected else '无'}",
        f"- 审核状态：{next_state.get('review_status', '') or '无'}",
        f"- 质量评分：{_format_score(next_state.get('quality_score'))}",
        "",
        "记忆系统：",
        f"- current_context：{'已生成' if memory.get('context_exists') else '未生成'}",
        f"- Obsidian 同步：{'已同步' if memory.get('obsidian_synced') else '未同步'}",
        f"- 向量库：{'已启用' if memory.get('vector_memory_enabled') else '未启用'}（{memory.get('vector_indexed_chapters', 0)} 章 {memory.get('vector_chunks', 0)} 片段）",
        f"- memory_index：{'存在' if memory.get('memory_index_exists') else '不存在'}",
        "",
        "质量风险：",
        f"- 风险等级：{quality.get('risk_level', 'unknown')}",
        "- 主要问题：",
    ]
    quality_index = max(len(lines) - 3, 0)
    lines[quality_index:quality_index] = _render_memory_health_lines(memory_health) + [""]
    flags = quality.get("main_flags", [])
    lines.extend([f"  - {item.get('message', '')}" for item in flags] if flags else ["  - 无"])
    lines.extend([
        "",
        "伏笔：",
        f"- open：{foreshadows.get('open_count', 0)}",
        f"- planned：{foreshadows.get('planned_count', 0)}",
        f"- resolved：{foreshadows.get('resolved_count', 0)}",
        "",
        "下一步建议：",
    ])
    lines.extend([
        f"- open：{todos.get('open_count', 0)}",
        f"- in_progress：{todos.get('in_progress_count', 0)}",
        f"- high：{todos.get('high_priority_count', 0)}",
        f"- urgent：{todos.get('urgent_count', 0)}",
        "",
        "优先处理：",
    ])
    top_todos = todos.get("top_items", [])
    lines.extend([f"{index}. {_todo_label(item)}" for index, item in enumerate(top_todos[:3], 1)] if top_todos else ["无"])
    lines.extend(["", "下一步建议："])
    lines.extend([
        "",
        "控制台：",
        f"- shell：{'可用' if shell.get('available') else '不可用'}",
        "- 启动命令：python main.py shell",
        f"- 最近日志：{shell.get('last_shell_log', '') or '无'}",
        "",
        "问答系统：",
        f"- ask-state：{'可用' if qa.get('ask_state_available') else '不可用'}",
        f"- ask-memory：{'可用' if qa.get('ask_memory_available') else '不可用'}",
        f"- ask-story：{'可用' if qa.get('ask_story_available') else '不可用'}",
        f"- 历史问答：{qa.get('logs_count', 0)} 条",
        "",
        "下一步建议：",
    ])
    for index, action in enumerate(actions, 1):
        lines.append(f"{index}. {action.get('command', '')}")
        lines.append(f"   原因：{action.get('reason', '')}")
    if full:
        lines.extend(_render_full(status))
    return "\n".join(lines) + "\n"


def save_status_report(status: dict[str, Any], data_dir: str | Path = "data") -> tuple[str, str]:
    root = Path(data_dir)
    directory = root / "status"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "latest_status.json"
    markdown_path = directory / "latest_status.md"
    json_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_status_text(status, full="details" in status), encoding="utf-8")
    return json_path.as_posix(), markdown_path.as_posix()


def collect_full_details(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    pipeline_runs = _safe_recent_pipeline_runs(root / "pipeline_runs")
    return {
        "recent_chapters": [path.as_posix() for path in sorted((root / "chapters").glob("chapter_*.md"))[-5:]],
        "quality_reports": [path.as_posix() for path in sorted((root / "quality_reports").glob("*.json"))],
        "pipeline_runs": [path.as_posix() for path in pipeline_runs[:5]],
        "config_summary": load_json_if_exists(".story_os/config.json", {}) or {},
    }


def _safe_recent_pipeline_runs(directory: Path) -> list[Path]:
    runs: list[tuple[float, Path]] = []
    if not directory.exists():
        return []
    for path in directory.glob("*.json"):
        try:
            runs.append((path.stat().st_mtime, path))
        except (PermissionError, FileNotFoundError, OSError) as exc:
            LOAD_WARNINGS.append(f"Unreadable pipeline run skipped: {path.as_posix()} ({exc.__class__.__name__})")
    return [path for _, path in sorted(runs, key=lambda item: item[0], reverse=True)]


def _render_memory_health_lines(memory_health: dict[str, Any]) -> list[str]:
    if not memory_health.get("exists"):
        return ["记忆健康：尚未检查"]
    return [
        f"记忆健康：{memory_health.get('overall_status', '')}",
        f"健康分：{memory_health.get('overall_score', 0)}",
        f"错误：{memory_health.get('errors', 0)}",
        f"警告：{memory_health.get('warnings', 0)}",
        f"信息：{memory_health.get('infos', 0)}",
        f"上次检查：{memory_health.get('last_checked_at', '')}",
    ]


def _render_full(status: dict[str, Any]) -> list[str]:
    versions = status.get("versions", {})
    foreshadows = status.get("foreshadows", {})
    health = status.get("health", {})
    details = status.get("details", {})
    lines = ["", "版本列表：", "[DRAFT]"]
    for item in versions.get("drafts", []):
        lines.append(f"- {item.get('version_label', '')} | {item.get('actual_word_count', 0)}字 | {item.get('mode', '')}")
    lines.append("[EDITED]")
    for item in versions.get("edited", []):
        lines.append(f"- {item.get('version_label', '')} | {item.get('actual_word_count', 0)}字 | {item.get('mode', '')}")
    lines.append("[MANUAL]")
    for item in versions.get("manual", []):
        source = f"{item.get('source_origin_type', '')}_v{int(item.get('source_origin_version', 0) or 0):03d}" if item.get("source_origin_type") else ""
        lines.append(f"- {item.get('version_label', '')} | {item.get('actual_word_count', 0)}字 | {item.get('mode', '')} | source={source}")
    lines.extend(["", "Open 伏笔："])
    for index, item in enumerate(foreshadows.get("open_items", []), 1):
        lines.append(f"{index}. {item.get('content', '')}")
    lines.extend([
        "",
        "质量报告：",
        *[f"- {path}" for path in details.get("quality_reports", [])],
        "",
        "最近 pipeline：",
        *[f"- {path}" for path in details.get("pipeline_runs", [])],
        "",
        "文件健康检查：",
        f"- missing_files: {health.get('missing_files', [])}",
        "- warnings:",
    ])
    lines.extend([f"  - {item}" for item in health.get("warnings", [])] or ["  - 无"])
    lines.append(f"- errors: {health.get('errors', [])}")
    return lines


def _current_target_chapter(root: Path) -> int:
    plan = load_json_if_exists(root / "next_chapter_plan.json", {}) or {}
    if plan.get("chapter_id"):
        return int(plan.get("chapter_id", 1) or 1)
    state = load_json_if_exists(root / "state.json", {}) or {}
    return int(state.get("current_chapter", 0) or 0) + 1


def _quality_source_for_chapter(chapter_id: int, root: Path) -> dict[str, Any]:
    versions = list_versions(chapter_id, root)
    selected = versions.get("selected", {})
    if isinstance(selected, dict) and selected.get("source_type") and selected.get("version"):
        return {"source_type": str(selected["source_type"]), "version": int(selected["version"])}
    if versions.get("manual"):
        item = versions["manual"][-1]
        return {"source_type": "manual", "version": int(item.get("version", 0) or 0)}
    if versions.get("edited"):
        item = versions["edited"][-1]
        return {"source_type": "edited", "version": int(item.get("version", 0) or 0)}
    if versions.get("drafts"):
        item = versions["drafts"][-1]
        return {"source_type": "draft", "version": int(item.get("version", 0) or 0)}
    return {}


def _risk_level(score: Any) -> str:
    if score is None:
        return "unknown"
    value = float(score)
    if value >= 0.8:
        return "low"
    if value >= 0.65:
        return "medium"
    return "high"


def _count_status(items: Any, status: str) -> int:
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get("status") == status)


def _format_score(score: Any) -> str:
    if score is None:
        return "未评估"
    return f"{float(score):.2f}"


def _version_label(item: dict[str, Any]) -> str:
    return str(item.get("version_label") or f"{item.get('source_type', '')}_v{int(item.get('version', 0) or 0):03d}")


def _todo_label(item: dict[str, Any]) -> str:
    return format_todo_for_cli(item)
