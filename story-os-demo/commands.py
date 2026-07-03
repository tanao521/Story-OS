from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import config
from config import DATA_DIR
from core.chapter_committer import commit_chapter, render_committed_chapter_markdown
from core.draft_editor import edit_draft, render_edited_markdown
from core.draft_writer import render_draft_markdown, write_chapter_draft
from core.next_chapter_planner import plan_next_chapter, render_next_chapter_plan_markdown
from core.setup_wizard import build_initial_state
from system.context_builder import build_working_context, save_current_context
from system.file_store import load_json, save_json, save_markdown
from system.memory_health import (
    render_memory_health_markdown,
    run_memory_health_check,
    save_memory_health_report,
)
from system.obsidian_sync import load_local_config, sync_to_obsidian
from system.self_check import run_self_check
from system.quality_checker import (
    build_quality_report,
    load_quality_report,
    quality_report_paths,
    quality_summary_from_report,
    save_quality_report,
)
from system.version_manager import (
    build_versioned_paths,
    get_next_version_number,
    list_versions,
    load_versions_index,
    read_version_payload,
    save_versions_index,
    select_version,
)


def build_context_command() -> dict[str, Any]:
    paths = _paths()
    if not paths["state"].exists():
        return _failed("build-context", "缺少 data/state.json，请先运行 python main.py setup。")

    state = load_json(str(paths["state"]))
    current_chapter = int(state.get("current_chapter", 0) or 0)
    if current_chapter == 0 and not paths["memory_index"].exists():
        warning = "当前还没有已提交章节，已跳过 build-context。"
        return _success("build-context", warning, warnings=[warning], outputs={"skipped": True})
    if not paths["memory_index"].exists():
        return _failed("build-context", "缺少 data/memory/memory_index.json。")

    memory_index = load_json(str(paths["memory_index"]))
    query = _build_context_query(state, paths)
    context = build_working_context(state, memory_index, query)
    json_path, markdown_path = save_current_context(context)
    state["current_stage"] = "context_built"
    state["context"] = {
        "created": True,
        "json_path": json_path,
        "markdown_path": markdown_path,
        "recent_raw_chapters": 3,
        "older_chapters_strategy": "summary_only",
    }
    save_json("data/state.json", state)
    return _success(
        "build-context",
        "当前写作上下文包已生成。",
        outputs={"json_path": json_path, "markdown_path": markdown_path},
        warnings=context.get("warnings", []),
    )


def plan_next_command() -> dict[str, Any]:
    paths = _paths()
    missing = _missing_plan_next_inputs(paths)
    if missing:
        return _failed("plan-next", missing)

    story_spec = load_json(str(paths["story_spec"]))
    blueprint = load_json(str(paths["blueprint"]))
    characters = load_json(str(paths["characters"]))
    world_bible = load_json(str(paths["world_bible"]))
    state = _load_or_create_state(story_spec)
    working_context = _load_optional_context(paths)
    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state, working_context)
    state["current_stage"] = "next_chapter_planned"
    state["next_chapter_plan"] = {
        "created": True,
        "chapter_id": plan.get("chapter_id", 1),
        "path": "data/next_chapter_plan.json",
    }
    save_json("data/next_chapter_plan.json", plan)
    save_markdown("data/next_chapter_plan.md", render_next_chapter_plan_markdown(plan))
    save_json("data/state.json", state)
    return _success(
        "plan-next",
        "下一章计划已生成。",
        outputs={"chapter_id": plan.get("chapter_id", 1), "path": "data/next_chapter_plan.json"},
    )


def write_draft_command() -> dict[str, Any]:
    paths = _paths()
    missing = _missing_write_draft_inputs(paths)
    if missing:
        return _failed("write-draft", missing)

    story_spec = load_json(str(paths["story_spec"]))
    blueprint = load_json(str(paths["blueprint"]))
    characters = load_json(str(paths["characters"]))
    world_bible = load_json(str(paths["world_bible"]))
    state = _load_or_create_state(story_spec)
    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    working_context = _load_optional_context(paths)
    draft = write_chapter_draft(
        story_spec,
        blueprint,
        characters,
        world_bible,
        state,
        chapter_plan,
        working_context,
    )
    return _save_draft_payload(draft, state, command_name="write-draft", message="当前章草稿已生成。")


def regenerate_draft_command() -> dict[str, Any]:
    result = write_draft_command()
    if result.get("status") == "success":
        result["name"] = "regenerate-draft"
        result["message"] = "当前章草稿已重新生成，并保存为新版本。"
    return result


def edit_draft_command(draft_version: int | None = None) -> dict[str, Any]:
    paths = _paths()
    if not paths["next_chapter_plan"].exists():
        return _failed("edit-draft", "缺少 data/next_chapter_plan.json，请先运行 python main.py plan-next。")
    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)

    draft_info, draft_warning = _resolve_draft_for_edit(chapter_id, draft_version)
    if not draft_info:
        return _failed("edit-draft", "缺少当前章草稿，请先运行 python main.py write-draft。")

    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    blueprint = load_json(str(paths["blueprint"])) if paths["blueprint"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    state = load_json(str(paths["state"])) if paths["state"].exists() else _load_or_create_state(story_spec)
    working_context = _load_optional_context(paths)
    draft = read_version_payload(draft_info) if draft_info.get("version") else load_json(str(draft_info["json_path"]))
    draft["source_draft_path"] = str(draft_info["json_path"])
    edited = edit_draft(draft, chapter_plan, story_spec, blueprint, characters, world_bible, state, working_context)
    return _save_edited_payload(
        edited,
        state,
        source_draft_version=int(draft_info.get("version", draft.get("version", 0)) or 0),
        command_name="edit-draft",
        message="当前章草稿已编辑。",
        extra_warnings=[draft_warning] if draft_warning else [],
    )


def reedit_draft_command(draft_version: int | None = None) -> dict[str, Any]:
    result = edit_draft_command(draft_version=draft_version)
    if result.get("status") == "success":
        result["name"] = "reedit-draft"
        result["message"] = "当前章已重新编辑，并保存为新编辑版本。"
    return result


def compare_drafts_command(select_spec: str | None = None) -> dict[str, Any]:
    paths = _paths()
    if not paths["next_chapter_plan"].exists():
        return _failed("compare-drafts", "缺少 data/next_chapter_plan.json，请先运行 python main.py plan-next。")
    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)
    selected: dict[str, Any] = {}
    warnings: list[str] = []
    if select_spec:
        try:
            source_type, version = _parse_select_spec(select_spec)
            selected = select_version(chapter_id, source_type, version)
        except Exception as exc:
            return _failed("compare-drafts", f"选择版本失败：{exc}")

    versions = load_versions_index(chapter_id)
    _attach_quality_metadata(versions)
    if not selected and isinstance(versions.get("selected"), dict):
        selected = versions.get("selected", {})
    if not versions.get("drafts") and not versions.get("edited") and not versions.get("manual"):
        warnings.append("当前章还没有可比较的草稿或编辑版本。")
    return _success(
        "compare-drafts",
        "版本列表已生成。",
        outputs={
            "chapter_id": chapter_id,
            "drafts": versions.get("drafts", []),
            "edited": versions.get("edited", []),
            "manual": versions.get("manual", []),
            "selected": selected,
            "versions_path": f"data/versions/chapter_{chapter_id:03d}_versions.json",
        },
        warnings=warnings,
    )



def quality_check_command(
    all_versions: bool = False,
    draft_version: int | None = None,
    edited_version: int | None = None,
    manual_version: int | None = None,
) -> dict[str, Any]:
    paths = _paths()
    if not paths["next_chapter_plan"].exists():
        return _failed("quality-check", "缺少 data/next_chapter_plan.json，请先运行 python main.py plan-next。")
    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)
    source_infos = _resolve_quality_sources(chapter_id, all_versions, draft_version, edited_version, manual_version)
    if not source_infos:
        return _failed("quality-check", "未找到可评估的当前章版本，请先运行 write-draft 或 edit-draft。")

    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    state = load_json(str(paths["state"])) if paths["state"].exists() else {}
    reports: list[dict[str, Any]] = []
    for source_info in source_infos:
        source = read_version_payload(source_info) if source_info.get("version") else load_json(str(source_info["json_path"]))
        source_type = str(source_info.get("source_type", ""))
        source_version = int(source_info.get("version", source.get("version", 0)) or 0)
        source_path = str(source_info.get("json_path", ""))
        report = build_quality_report(
            source,
            source_type,
            source_version,
            source_path,
            chapter_plan,
            story_spec,
            characters,
            world_bible,
            state,
            use_llm=bool(getattr(config, "USE_DEEPSEEK_FOR_QUALITY_CHECK", False)),
        )
        json_path, markdown_path = save_quality_report(report)
        reports.append({
            "chapter_id": report["chapter_id"],
            "source_type": source_type,
            "source_version": source_version,
            "version_label": source_info.get("version_label", f"{source_type}_v{source_version:03d}"),
            "overall_score": report["overall_score"],
            "json_path": json_path,
            "markdown_path": markdown_path,
            "flags": report.get("flags", []),
        })
    first = reports[0]
    return _success(
        "quality-check",
        "质量评估完成。",
        outputs={
            "chapter_id": chapter_id,
            "reports": reports,
            "report": first,
            "report_count": len(reports),
        },
    )


def quality_summary_for_target(target: dict[str, Any], data_dir: str | Path = "data") -> dict[str, Any]:
    source_version = int(target.get("version", 0) or 0)
    if source_version <= 0:
        return {}
    report = load_quality_report(
        int(target.get("chapter_id", 1) or 1),
        str(target.get("source_type", "")),
        source_version,
        data_dir,
    )
    return quality_summary_from_report(report)


def commit_chapter_command() -> dict[str, Any]:
    paths = _paths()
    if not paths["state"].exists():
        return _failed("commit-chapter", "缺少 data/state.json，请先运行 python main.py setup。")
    if not paths["next_chapter_plan"].exists():
        return _failed("commit-chapter", "缺少 data/next_chapter_plan.json，请先运行 python main.py plan-next。")

    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)
    source_info, source_warnings = _resolve_commit_source(chapter_id)
    if not source_info:
        return _failed("commit-chapter", "缺少当前章草稿，请先运行 python main.py write-draft。")

    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    draft = read_version_payload(source_info) if source_info.get("version") else load_json(str(source_info["json_path"]))
    draft["source_path"] = str(source_info["json_path"])
    draft["source_version"] = int(source_info.get("version", draft.get("version", 0)) or 0)
    state = load_json(str(paths["state"]))
    result = commit_chapter(draft, chapter_plan, state, story_spec, characters, world_bible)
    result["source_version"] = int(source_info.get("version", draft.get("version", 0)) or 0)
    result["source_path"] = str(source_info.get("json_path", ""))
    save_markdown(result["chapter_path"], render_committed_chapter_markdown(draft))
    save_json(result["summary_path"], result["summary"])
    save_json("data/state.json", state)
    warnings = list(result.get("warnings", [])) + source_warnings
    return _success(
        "commit-chapter",
        "当前章已提交。",
        outputs={
            "chapter_id": result.get("chapter_id"),
            "chapter_path": result.get("chapter_path"),
            "summary_path": result.get("summary_path"),
            "source_used": result.get("source_used"),
            "source_version": result.get("source_version"),
            "source_path": result.get("source_path"),
        },
        warnings=warnings,
    )


def sync_obsidian_command() -> dict[str, Any]:
    paths = _paths()
    if not paths["story_spec"].exists():
        return _failed("sync-obsidian", "缺少 data/story_spec.json。")
    local_config = load_local_config()
    vault_dir = local_config.get("obsidian_vault_dir")
    if not vault_dir:
        return _failed("sync-obsidian", "未配置 obsidian_vault_dir。")
    project_name = local_config.get("obsidian_project_dir_name", "StoryOS")
    result = sync_to_obsidian(DATA_DIR, vault_dir, project_name)
    if paths["state"].exists():
        state = load_json(str(paths["state"]))
        state["current_stage"] = "obsidian_synced"
        state["obsidian"] = {
            "synced": True,
            "vault_dir": result.get("obsidian_vault_dir", ""),
            "project_root": result.get("obsidian_project_root", ""),
            "index_path": result.get("index_path", ""),
            "sync_version": result.get("sync_version", "0.8"),
        }
        save_json("data/state.json", state)
    return _success("sync-obsidian", "Obsidian 同步完成。", outputs=result, warnings=result.get("warnings", []))


def index_vault_command() -> dict[str, Any]:
    paths = _paths()
    local_config = load_local_config()
    index_data = {
        "index_version": "1.5",
        "mode": "lightweight_placeholder",
        "obsidian_vault_dir": local_config.get("obsidian_vault_dir", ""),
        "obsidian_project_dir_name": local_config.get("obsidian_project_dir_name", "StoryOS"),
        "memory_index_exists": paths["memory_index"].exists(),
        "versions_supported": True,
    }
    save_json("data/vault_index.json", index_data)
    return _success("index-vault", "Vault 轻量索引已更新。", outputs={"path": "data/vault_index.json"})



def self_check_command(json_output: bool = False) -> dict[str, Any]:
    import json

    report = run_self_check(".")
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "OK" if report.get("ok") else "ERROR"
        summary = report.get("summary", {})
        print("Story OS Self Check")
        print()
        print(f"Status: {status}")
        print(f"Errors: {summary.get('errors', 0)}")
        print(f"Warnings: {summary.get('warnings', 0)}")
        print(f"Infos: {summary.get('infos', 0)}")
        if report.get("warnings"):
            print()
            print("Warnings:")
            for item in report.get("warnings", []):
                print(f"- {item}")
        if report.get("errors"):
            print()
            print("Errors:")
            for item in report.get("errors", []):
                print(f"- {item}")
    return report


def memory_health_command(json_output: bool = False, full: bool = False) -> dict[str, Any]:
    import json

    report = run_memory_health_check(DATA_DIR, full=full)
    paths = save_memory_health_report(report, DATA_DIR)
    report["report_paths"] = paths
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        markdown = render_memory_health_markdown(report)
        lines = markdown.splitlines()
        print("\n".join(lines[:18]))
        if len(lines) > 18:
            print("...")
        print(f"\nReport saved: {paths['json_path']} / {paths['markdown_path']}")
    return report


def run_chapter_command(auto_commit: bool = False) -> dict[str, Any]:
    from system.pipeline_runner import run_single_chapter_pipeline

    report = run_single_chapter_pipeline(auto_commit=auto_commit)
    status = str(report.get("status", ""))
    if status == "failed":
        errors = report.get("errors", [])
        message = str(errors[0]) if errors else "单章流水线失败。"
        return _failed("run-chapter", message)
    message = "已生成到待审核状态。" if status == "waiting_for_review" else "单章流水线完成。"
    return _success(
        "run-chapter",
        message,
        outputs=report,
        warnings=list(report.get("warnings", []) or []),
    )

def draft_paths(chapter_id: int) -> tuple[Path, Path]:
    file_stem = f"chapter_{chapter_id:03d}_draft"
    return Path("data/drafts") / f"{file_stem}.json", Path("data/drafts") / f"{file_stem}.md"


def edited_paths(chapter_id: int) -> tuple[Path, Path]:
    file_stem = f"chapter_{chapter_id:03d}_edited"
    return Path("data/edited") / f"{file_stem}.json", Path("data/edited") / f"{file_stem}.md"


def _save_draft_payload(
    draft: dict[str, Any],
    state: dict[str, Any],
    command_name: str,
    message: str,
) -> dict[str, Any]:
    chapter_id = int(draft.get("chapter_id", 1) or 1)
    version = get_next_version_number(chapter_id, "draft")
    version_paths = build_versioned_paths(chapter_id, "draft", version)
    latest_json_path, latest_markdown_path = draft_paths(chapter_id)
    draft["version"] = version
    draft["version_label"] = f"draft_v{version:03d}"
    draft["created_at"] = _now()
    markdown = render_draft_markdown(draft)
    save_json(version_paths["json_path"], draft)
    save_markdown(version_paths["markdown_path"], markdown)
    save_json(str(latest_json_path), draft)
    save_markdown(str(latest_markdown_path), markdown)
    versions = load_versions_index(chapter_id)
    save_versions_index(chapter_id, versions)
    state["current_stage"] = "chapter_draft_created"
    state["draft"] = {
        "created": True,
        "chapter_id": chapter_id,
        "status": "draft",
        "version": version,
        "version_label": draft["version_label"],
        "json_path": latest_json_path.as_posix(),
        "markdown_path": latest_markdown_path.as_posix(),
        "versioned_json_path": version_paths["json_path"],
        "versioned_markdown_path": version_paths["markdown_path"],
    }
    save_json("data/state.json", state)
    return _success(
        command_name,
        message,
        outputs={
            "chapter_id": chapter_id,
            "version": version,
            "version_label": draft["version_label"],
            "json_path": latest_json_path.as_posix(),
            "markdown_path": latest_markdown_path.as_posix(),
            "versioned_json_path": version_paths["json_path"],
            "versioned_markdown_path": version_paths["markdown_path"],
            "generation": draft.get("generation", {}),
        },
        warnings=draft.get("generation", {}).get("warnings", []),
    )


def _save_edited_payload(
    edited: dict[str, Any],
    state: dict[str, Any],
    source_draft_version: int,
    command_name: str,
    message: str,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    chapter_id = int(edited.get("chapter_id", 1) or 1)
    version = get_next_version_number(chapter_id, "edited")
    version_paths = build_versioned_paths(chapter_id, "edited", version)
    latest_json_path, latest_markdown_path = edited_paths(chapter_id)
    edited["version"] = version
    edited["version_label"] = f"edited_v{version:03d}"
    edited["source_draft_version"] = source_draft_version
    edited["created_at"] = _now()
    markdown = render_edited_markdown(edited)
    save_json(version_paths["json_path"], edited)
    save_markdown(version_paths["markdown_path"], markdown)
    save_json(str(latest_json_path), edited)
    save_markdown(str(latest_markdown_path), markdown)
    versions = load_versions_index(chapter_id)
    save_versions_index(chapter_id, versions)
    state["current_stage"] = "chapter_draft_edited"
    state["edited"] = {
        "created": True,
        "chapter_id": chapter_id,
        "status": "edited",
        "version": version,
        "version_label": edited["version_label"],
        "source_draft_version": source_draft_version,
        "json_path": latest_json_path.as_posix(),
        "markdown_path": latest_markdown_path.as_posix(),
        "versioned_json_path": version_paths["json_path"],
        "versioned_markdown_path": version_paths["markdown_path"],
    }
    save_json("data/state.json", state)
    warnings = list(extra_warnings or []) + list(edited.get("editing", {}).get("warnings", []))
    return _success(
        command_name,
        message,
        outputs={
            "chapter_id": chapter_id,
            "version": version,
            "version_label": edited["version_label"],
            "source_draft_version": source_draft_version,
            "json_path": latest_json_path.as_posix(),
            "markdown_path": latest_markdown_path.as_posix(),
            "versioned_json_path": version_paths["json_path"],
            "versioned_markdown_path": version_paths["markdown_path"],
            "editing": edited.get("editing", {}),
        },
        warnings=warnings,
    )



def _resolve_quality_sources(
    chapter_id: int,
    all_versions: bool,
    draft_version: int | None,
    edited_version: int | None,
    manual_version: int | None,
) -> list[dict[str, Any]]:
    versions = load_versions_index(chapter_id)
    if all_versions:
        return list(versions.get("drafts", [])) + list(versions.get("edited", [])) + list(versions.get("manual", []))
    if draft_version is not None:
        return [_find_version_info(versions, "draft", draft_version)] if _find_version_info(versions, "draft", draft_version) else []
    if edited_version is not None:
        return [_find_version_info(versions, "edited", edited_version)] if _find_version_info(versions, "edited", edited_version) else []
    if manual_version is not None:
        return [_find_version_info(versions, "manual", manual_version)] if _find_version_info(versions, "manual", manual_version) else []
    selected = versions.get("selected", {})
    if isinstance(selected, dict) and selected.get("source_type") and selected.get("version"):
        found = _find_version_info(versions, str(selected["source_type"]), int(selected["version"]))
        if found:
            return [found]
    if versions.get("manual"):
        return [versions["manual"][-1]]
    if versions.get("edited"):
        return [versions["edited"][-1]]
    if versions.get("drafts"):
        return [versions["drafts"][-1]]
    return []


def _find_version_info(versions: dict[str, Any], source_type: str, version: int) -> dict[str, Any]:
    key = "drafts" if source_type == "draft" else source_type
    for item in versions.get(key, []):
        if int(item.get("version", 0) or 0) == version and Path(str(item.get("json_path", ""))).exists():
            return item
    return {}


def _attach_quality_metadata(versions: dict[str, Any]) -> None:
    for key in ["drafts", "edited", "manual"]:
        for item in versions.get(key, []):
            report = load_quality_report(
                int(item.get("chapter_id", versions.get("chapter_id", 1)) or 1),
                str(item.get("source_type", "")),
                int(item.get("version", 0) or 0),
            )
            if report:
                item["quality_score"] = report.get("overall_score")
                item["quality_ai_risk"] = quality_summary_from_report(report).get("ai_risk", "low")
                item["quality_report_path"] = quality_report_paths(
                    int(report.get("chapter_id", 1) or 1),
                    str(report.get("source_type", "")),
                    int(report.get("source_version", 0) or 0),
                )[1].as_posix()
            else:
                item["quality_score"] = None
                item["quality_ai_risk"] = ""
                item["quality_report_path"] = ""


def _resolve_draft_for_edit(chapter_id: int, draft_version: int | None) -> tuple[dict[str, Any], str]:
    versions = load_versions_index(chapter_id)
    if draft_version is not None:
        for item in versions.get("drafts", []):
            if int(item.get("version", 0) or 0) == draft_version and Path(str(item.get("json_path", ""))).exists():
                return item, ""
        return {}, f"未找到 draft:{draft_version}，请先运行 compare-drafts 查看可用版本。"
    drafts = versions.get("drafts", [])
    if drafts:
        return drafts[-1], ""
    latest_json, latest_md = draft_paths(chapter_id)
    if latest_json.exists():
        return {
            "source_type": "draft",
            "version": 0,
            "version_label": "draft_latest",
            "json_path": latest_json.as_posix(),
            "markdown_path": latest_md.as_posix(),
        }, "当前使用兼容草稿文件，未找到版本化草稿。"
    return {}, ""


def _resolve_commit_source(chapter_id: int) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    versions = load_versions_index(chapter_id)
    selected = versions.get("selected", {})
    if isinstance(selected, dict) and selected.get("source_type") and selected.get("version"):
        source_type = str(selected["source_type"])
        selected_version = int(selected["version"])
        collection_key = "drafts" if source_type == "draft" else source_type
        for item in versions.get(collection_key, []):
            if int(item.get("version", 0) or 0) == selected_version and Path(str(item.get("json_path", ""))).exists():
                return item, warnings
        warnings.append("选中版本不存在，已回退到最新可用版本。")

    manual_versions = versions.get("manual", [])
    if manual_versions:
        return manual_versions[-1], warnings
    edited_versions = versions.get("edited", [])
    if edited_versions:
        return edited_versions[-1], warnings
    draft_versions = versions.get("drafts", [])
    if draft_versions:
        return draft_versions[-1], warnings

    edited_json, edited_md = edited_paths(chapter_id)
    draft_json, draft_md = draft_paths(chapter_id)
    if edited_json.exists():
        return {
            "source_type": "edited",
            "version": 0,
            "version_label": "edited_latest",
            "json_path": edited_json.as_posix(),
            "markdown_path": edited_md.as_posix(),
        }, warnings
    if draft_json.exists():
        return {
            "source_type": "draft",
            "version": 0,
            "version_label": "draft_latest",
            "json_path": draft_json.as_posix(),
            "markdown_path": draft_md.as_posix(),
        }, warnings
    return {}, warnings


def _parse_select_spec(select_spec: str) -> tuple[str, int]:
    if ":" not in select_spec:
        raise ValueError("格式应为 edited:1 或 draft:2")
    source_type, raw_version = select_spec.split(":", 1)
    source_type = source_type.strip().lower()
    if source_type not in {"draft", "edited", "manual"}:
        raise ValueError("type must be draft, edited, or manual")
    version = int(raw_version.strip())
    if version <= 0:
        raise ValueError("版本号必须大于 0")
    return source_type, version


def _paths() -> dict[str, Path]:
    return {
        "story_spec": Path("data/story_spec.json"),
        "state": Path("data/state.json"),
        "blueprint": Path("data/story_blueprint.json"),
        "characters": Path("data/characters.json"),
        "world_bible": Path("data/world_bible.json"),
        "next_chapter_plan": Path("data/next_chapter_plan.json"),
        "memory_index": Path("data/memory/memory_index.json"),
        "current_context": Path("data/context/current_context.json"),
    }


def _missing_plan_next_inputs(paths: dict[str, Path]) -> str:
    if not paths["story_spec"].exists():
        return "缺少 data/story_spec.json。"
    if not paths["blueprint"].exists():
        return "缺少 data/story_blueprint.json。"
    if not paths["characters"].exists() or not paths["world_bible"].exists():
        return "缺少角色卡或世界观设定，请先运行 python main.py build-assets。"
    return ""


def _missing_write_draft_inputs(paths: dict[str, Path]) -> str:
    missing = _missing_plan_next_inputs(paths)
    if missing:
        return missing
    if not paths["next_chapter_plan"].exists():
        return "缺少 data/next_chapter_plan.json。"
    return ""


def _load_optional_context(paths: dict[str, Path]) -> dict[str, Any] | None:
    if paths["current_context"].exists():
        return load_json(str(paths["current_context"]))
    return None


def _load_or_create_state(story_spec: dict[str, Any]) -> dict[str, Any]:
    state_path = Path("data/state.json")
    if state_path.exists():
        return load_json(str(state_path))
    return build_initial_state(story_spec)


def _build_context_query(state: dict[str, Any], paths: dict[str, Path]) -> str:
    parts = []
    plot = state.get("plot", {})
    if isinstance(plot, dict):
        parts.append(str(plot.get("main_arc", "")))
        completed = plot.get("completed_events", [])
        if isinstance(completed, list):
            parts.extend(str(item) for item in completed[-3:])
    foreshadows = state.get("foreshadows", [])
    if isinstance(foreshadows, list):
        parts.extend(
            str(item.get("content", ""))
            for item in foreshadows
            if isinstance(item, dict) and item.get("status") in {"open", "planned"}
        )
    if paths["next_chapter_plan"].exists():
        plan = load_json(str(paths["next_chapter_plan"]))
        parts.append(str(plan.get("chapter_goal", "")))
        parts.append(str(plan.get("conflict_design", {}).get("main_conflict", "")))
        parts.append(str(plan.get("pacing_design", {}).get("ending_hook", "")))
    return " ".join(part for part in parts if part)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _success(
    name: str,
    message: str,
    outputs: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "success",
        "message": message,
        "outputs": outputs or {},
        "warnings": [warning for warning in (warnings or []) if warning],
    }


def _failed(name: str, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "failed",
        "message": message,
        "outputs": {},
        "warnings": [],
    }
