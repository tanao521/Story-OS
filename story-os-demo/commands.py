from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import config
from config import DATA_DIR
from core.blueprint_generator import generate_blueprint, render_blueprint_markdown
from core.chapter_committer import commit_chapter, render_committed_chapter_markdown
from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy
from core.character_builder import generate_characters, render_characters_markdown
from core.draft_editor import edit_draft, render_edited_markdown
from core.draft_writer import render_draft_markdown, write_chapter_draft
from core.next_chapter_planner import plan_next_chapter, render_next_chapter_plan_markdown
from core.project import ensure_project_structure, resolve_current_project_root, resolve_workspace_root
from core.project_context import get_project_context
from core.contracts import HashGuard, ProjectRef
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible, render_world_bible_markdown
from llm.planning_service import (
    create_deepseek_client,
    generate_blueprint_with_deepseek,
    plan_next_chapter_with_deepseek,
    should_use_deepseek_for_planning,
)
from system.context_assembly_service import ContextAssemblyService
from system.context_builder import save_current_context
from system.file_store import load_json, save_json, save_markdown
from system.planning_service import load_planning
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
from system.validators import validate_story_spec
from system.version_manager import (
    build_versioned_paths,
    get_next_version_number,
    list_versions,
    load_versions_index,
    read_version_payload,
    save_versions_index,
    select_version,
)
from system.version_writer_facade import VersionWriterFacade
from system.project_manager import get_project_manager, ProjectManagerError


def _refresh_current_context_after_commit(paths: dict[str, Path], state: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Persist a fresh context without changing the commit workflow stage."""
    memory_index = load_json(str(paths["memory_index"]))
    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    context = ContextAssemblyService(get_project_context()).assemble(
        state=state, memory_index=memory_index, query=_build_context_query(state, paths),
        story_spec=story_spec, characters=characters, world_bible=world_bible,
        purpose="chapter_drafting",
    )
    try:
        planning = load_planning(get_project_context())
        current = int(state.get("current_chapter", 0) or 0) + 1
        chapter_plan = next((item for item in planning.get("chapters", []) if int(item.get("chapter_number", item.get("chapter_id", -1)) or -1) == current), None)
        context["planning_context"] = {"chapter_plan": chapter_plan or {}, "active_threads": [item for item in planning.get("plot_threads", []) if item.get("status") == "active"], "open_foreshadowing": [item for item in planning.get("foreshadowing", []) if item.get("status") not in {"resolved", "abandoned"}]}
    except Exception:
        context["planning_context"] = {}
    json_path, markdown_path = save_current_context(context)
    return context, json_path, markdown_path

import re

def _extract_version_number(source_version_id: str | None) -> int:
    if not source_version_id:
        return 0
    # Prefer _vNNN suffix (e.g. chapter_001_manual_v002.json -> 2)
    match = re.search(r"_v(\d+)", str(source_version_id))
    if match:
        return int(match.group(1))
    # Fallback to vNNN anywhere (e.g. draft_v001 -> 1)
    match = re.search(r"v(\d+)", str(source_version_id))
    return int(match.group(1)) if match else 0

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
    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    query = _build_context_query(state, paths)
    context = ContextAssemblyService(get_project_context()).assemble(
        state=state, memory_index=memory_index, query=query, story_spec=story_spec,
        characters=characters, world_bible=world_bible, purpose="chapter_drafting",
    )
    try:
        planning = load_planning(get_project_context())
        current = int(state.get("current_chapter", 0) or 0) + 1
        chapter_plan = next((item for item in planning.get("chapters", []) if int(item.get("chapter_number", item.get("chapter_id", -1)) or -1) == current), None)
        context["planning_context"] = {"chapter_plan": chapter_plan or {}, "active_threads": [item for item in planning.get("plot_threads", []) if item.get("status") == "active"], "open_foreshadowing": [item for item in planning.get("foreshadowing", []) if item.get("status") not in {"resolved", "abandoned"}]}
    except Exception:
        context["planning_context"] = {}
    json_path, markdown_path = save_current_context(context)
    state["current_stage"] = "context_built"
    state["context"] = {
        "created": True,
        "json_path": json_path,
        "markdown_path": markdown_path,
        "recent_raw_chapters": 3,
        "older_chapters_strategy": "summary_only",
    }
    save_json(str(_paths()["state"]), state)
    return _success(
        "build-context",
        "当前写作上下文包已生成。",
        outputs={"json_path": json_path, "markdown_path": markdown_path},
        warnings=context.get("warnings", []),
    )



def generate_blueprint_command(force: bool = False, use_deepseek: bool | None = None) -> dict[str, Any]:
    """Generate the high-level story blueprint and persist its planning metadata."""
    project_root = resolve_current_project_root()
    structure = ensure_project_structure(project_root)
    paths = _paths(project_root)
    if not paths["story_spec"].exists():
        return _failed("generate-blueprint", "缺少 data/story_spec.json，请先创建小说项目。")
    story_spec = load_json(str(paths["story_spec"]))
    errors = validate_story_spec(story_spec)
    if errors:
        return _failed("generate-blueprint", "项目设定校验失败：" + "；".join(errors))
    if paths["blueprint"].exists() and not force:
        existing = load_json(str(paths["blueprint"]))
        if _blueprint_is_ready(existing):
            return _success(
                "generate-blueprint",
                "故事蓝图已存在，未覆盖现有内容。",
                outputs={"path": "data/story_blueprint.json", "mode": existing.get("generation_meta", {}).get("mode", "stored")},
            )
    blueprint = generate_blueprint(story_spec)
    client, warnings = _planning_client_for_web(story_spec, use_deepseek=use_deepseek)
    mode = "local_template"
    if client is not None:
        blueprint, planning_warnings = generate_blueprint_with_deepseek(story_spec, blueprint, client)
        warnings.extend(planning_warnings)
        mode = "deepseek"
    blueprint["generation_meta"] = {"mode": mode, "generated_at": _now(), "source": "web" if mode == "deepseek" else "local_fallback"}
    state = load_json(str(paths["state"])) if paths["state"].exists() else build_initial_state(story_spec)
    state["current_stage"] = "blueprint_created"
    state["blueprint"] = {"created": True, "path": "data/story_blueprint.json", "mode": "chapter_by_chapter"}
    save_json(str(paths["blueprint"]), blueprint)
    save_markdown(str(project_root / "data" / "story_blueprint.md"), render_blueprint_markdown(blueprint))
    save_json(str(paths["state"]), state)
    warnings.extend(str(item) for item in structure.get("events", []) if "loaded" not in str(item))
    return _success(
        "generate-blueprint",
        "故事蓝图已生成。" if mode == "deepseek" else "故事蓝图已生成（当前使用本地规划模板，可在配置 DeepSeek 后重新生成）。",
        outputs={"path": "data/story_blueprint.json", "mode": mode, "phase_count": len(blueprint.get("story_phases", []))},
        warnings=warnings,
    )


def build_assets_command(force: bool = False) -> dict[str, Any]:
    """Build character profiles and world bible from the current blueprint."""
    project_root = resolve_current_project_root()
    ensure_project_structure(project_root)
    paths = _paths(project_root)
    if not paths["story_spec"].exists() or not paths["blueprint"].exists():
        return _failed("build-assets", "请先生成故事蓝图。")
    story_spec = load_json(str(paths["story_spec"]))
    blueprint = load_json(str(paths["blueprint"]))
    existing_characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    existing_world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    if not force and _characters_are_ready(existing_characters) and _world_bible_is_ready(existing_world_bible):
        return _success("build-assets", "角色档案已存在，未覆盖现有内容。", outputs={"characters_path": "data/characters.json"})
    state = load_json(str(paths["state"])) if paths["state"].exists() else build_initial_state(story_spec)
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    state["current_stage"] = "assets_created"
    state["assets"] = {"characters_created": True, "world_bible_created": True, "characters_path": "data/characters.json", "world_bible_path": "data/world_bible.json"}
    state["characters"] = {
        character.get("name", character.get("id", "")): {
            "physical": character.get("current_state", {}).get("physical", ""),
            "mental": character.get("current_state", {}).get("mental", ""),
            "goal": character.get("external_goal", ""),
        }
        for character in characters.get("main_characters", [])
        if isinstance(character, dict)
    }
    blueprint["character_bible"] = {
        "protagonist": characters.get("main_characters", [{}])[0] if characters.get("main_characters") else {},
        "key_characters": characters.get("supporting_characters", []),
        "relationship_map": characters.get("relationship_map", []),
    }
    save_json(str(paths["characters"]), characters)
    save_markdown(str(project_root / "data" / "characters.md"), render_characters_markdown(characters))
    save_json(str(paths["world_bible"]), world_bible)
    save_markdown(str(project_root / "data" / "world_bible.md"), render_world_bible_markdown(world_bible))
    save_json(str(paths["blueprint"]), blueprint)
    save_markdown(str(project_root / "data" / "story_blueprint.md"), render_blueprint_markdown(blueprint))
    save_json(str(paths["state"]), state)
    return _success(
        "build-assets",
        "角色档案和世界观设定已生成。",
        outputs={"characters_path": "data/characters.json", "world_bible_path": "data/world_bible.json", "main_characters": len(characters.get("main_characters", [])), "supporting_characters": len(characters.get("supporting_characters", []))},
    )


def initialize_planning_command(use_deepseek: bool = False) -> dict[str, Any]:
    """Complete the planning bootstrap immediately after first project creation."""
    blueprint_result = generate_blueprint_command(force=True, use_deepseek=use_deepseek)
    if blueprint_result.get("status") == "failed":
        return blueprint_result

    assets_result = build_assets_command(force=True)
    if assets_result.get("status") == "failed":
        return _success(
            "initialize-planning",
            "故事蓝图已生成，但角色档案和世界观设定生成失败。",
            outputs={"blueprint": blueprint_result.get("outputs", {})},
            warnings=list(blueprint_result.get("warnings", [])) + [str(assets_result.get("message", "角色档案生成失败"))],
        )

    plan_result = plan_next_command(use_deepseek=use_deepseek)
    warnings = list(blueprint_result.get("warnings", [])) + list(assets_result.get("warnings", [])) + list(plan_result.get("warnings", []))
    if plan_result.get("status") == "failed":
        return _success(
            "initialize-planning",
            "故事蓝图、角色档案和世界观设定已完成，但首章计划生成失败。",
            outputs={"blueprint": blueprint_result.get("outputs", {}), "assets": assets_result.get("outputs", {})},
            warnings=warnings + [str(plan_result.get("message", "首章计划生成失败"))],
        )

    paths = _paths(resolve_current_project_root())
    blueprint = load_json(str(paths["blueprint"]))
    first_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_plan = blueprint.get("chapter_plan", [])
    if not isinstance(chapter_plan, list):
        chapter_plan = []
    blueprint["chapter_plan"] = [first_plan] if not chapter_plan else chapter_plan
    save_json(str(paths["blueprint"]), blueprint)
    save_markdown(str(resolve_current_project_root() / "data" / "story_blueprint.md"), render_blueprint_markdown(blueprint))

    outputs = {
        "blueprint": blueprint_result.get("outputs", {}),
        "assets": assets_result.get("outputs", {}),
        "first_chapter_plan": plan_result.get("outputs", {}),
        "initialized": True,
    }
    return _success("initialize-planning", "故事蓝图、角色档案、世界观设定和首章计划已完成初始化。", outputs=outputs, warnings=warnings)


def _planning_client_for_web(story_spec: dict[str, Any], use_deepseek: bool | None = None) -> tuple[Any | None, list[str]]:
    local_config = load_local_config()
    enabled = bool(local_config.get("use_deepseek_for_planning", False)) if use_deepseek is None else bool(use_deepseek)
    if not enabled:
        return None, ["DeepSeek 规划层未启用，已使用本地规划模板。"]
    if not config.DEEPSEEK_API_KEY:
        return None, ["已启用 DeepSeek 规划层，但未检测到 DEEPSEEK_API_KEY，已使用本地规划模板。"]
    if not should_use_deepseek_for_planning({**local_config, "use_deepseek_for_planning": True}):
        return None, ["DeepSeek 规划层配置不完整，已使用本地规划模板。"]
    return create_deepseek_client(), []


def _blueprint_is_ready(blueprint: Any) -> bool:
    return isinstance(blueprint, dict) and bool(blueprint.get("main_arc") and blueprint.get("story_phases"))


def _characters_are_ready(characters: Any) -> bool:
    return isinstance(characters, dict) and bool(characters.get("main_characters"))

def _world_bible_is_ready(world_bible: Any) -> bool:
    return isinstance(world_bible, dict) and bool(world_bible.get("core_rules"))


def plan_next_command(use_deepseek: bool | None = None) -> dict[str, Any]:
    project_root = resolve_current_project_root()
    structure = ensure_project_structure(project_root)
    paths = _paths(project_root)
    warnings: list[str] = []
    if not paths["story_spec"].exists():
        return _failed("plan-next", "缺少 data/story_spec.json，请先创建小说项目。")
    story_spec = load_json(str(paths["story_spec"]))
    if not paths["blueprint"].exists() or not _blueprint_is_ready(load_json(str(paths["blueprint"]))):
        blueprint_result = generate_blueprint_command(force=True)
        warnings.extend(blueprint_result.get("warnings", []))
        if blueprint_result.get("status") == "failed":
            return blueprint_result
    if not paths["characters"].exists() or not _characters_are_ready(load_json(str(paths["characters"]))) or not paths["world_bible"].exists() or not _world_bible_is_ready(load_json(str(paths["world_bible"]))):
        assets_result = build_assets_command(force=True)
        warnings.extend(assets_result.get("warnings", []))
        if assets_result.get("status") == "failed":
            return assets_result

    blueprint = load_json(str(paths["blueprint"]))
    characters = load_json(str(paths["characters"]))
    world_bible = load_json(str(paths["world_bible"]))
    state = load_json(str(paths["state"])) if paths["state"].exists() else build_initial_state(story_spec)
    working_context = _load_optional_context(paths)
    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state, working_context)
    client, planning_warnings = _planning_client_for_web(story_spec, use_deepseek=use_deepseek)
    warnings.extend(planning_warnings)
    if client is not None:
        plan, deepseek_warnings = plan_next_chapter_with_deepseek(story_spec, blueprint, characters, world_bible, state, working_context, plan, client)
        warnings.extend(deepseek_warnings)
        plan["generation_meta"] = {"mode": "deepseek", "generated_at": _now()}
    else:
        plan["generation_meta"] = {"mode": "local_template", "generated_at": _now()}
    state["current_stage"] = "next_chapter_planned"
    state["next_chapter_plan"] = {"created": True, "chapter_id": plan.get("chapter_id", 1), "path": "data/next_chapter_plan.json"}
    save_json(str(paths["next_chapter_plan"]), plan)
    save_markdown(str(project_root / "data" / "next_chapter_plan.md"), render_next_chapter_plan_markdown(plan))
    save_json(str(paths["state"]), state)
    return _success(
        "plan-next",
        "下一章计划已生成，后续正文将以该计划和故事蓝图为约束。",
        outputs={"chapter_id": plan.get("chapter_id", 1), "path": "data/next_chapter_plan.json", "project_root": str(project_root), "blueprint_path": structure["blueprint_path"].as_posix(), "mode": plan["generation_meta"]["mode"]},
        warnings=warnings,
    )


def write_draft_command(require_model: bool = False) -> dict[str, Any]:
    paths = _paths()
    missing = _missing_write_draft_inputs(paths)
    if missing:
        return _failed("write-draft", missing)
    config_error = _write_model_config_error() if require_model else ""
    if config_error:
        return _failed("write-draft", config_error)

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
    generation = draft.get("generation", {}) if isinstance(draft.get("generation", {}), dict) else {}
    if generation.get("mode") not in {"api_model", "ollama_cloud"}:
        warnings = generation.get("warnings", []) if isinstance(generation.get("warnings", []), list) else []
        detail = "; ".join(str(item) for item in warnings if item)
        message = "云端模型没有成功生成正文，已拒绝保存 mock 草稿。"
        if detail:
            message = f"{message} {detail}"
        return _failed("write-draft", message)
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
    warnings: list[str] = []
    versions: dict[str, Any] = {}
    chapter_id = 1

    # Resolve chapter_id from next_chapter_plan or state
    if paths["next_chapter_plan"].exists():
        chapter_plan = load_json(str(paths["next_chapter_plan"]))
        chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)
    elif paths["state"].exists():
        state = load_json(str(paths["state"]))
        chapter_id = int(state.get("current_chapter", 0) or 0)

    # Try to load version index even without a plan file
    try:
        versions = load_versions_index(chapter_id)
        _attach_quality_metadata(versions)
    except Exception:
        pass

    committed = _scan_committed_chapters(data_dir=get_project_context().data_dir)
    if chapter_id > 0 and not versions.get("drafts") and not versions.get("edited") and not versions.get("manual"):
        try:
            versions = load_versions_index(chapter_id - 1)
            _attach_quality_metadata(versions)
            warnings.append(f"当前章无版本数据，已回退到第 {chapter_id - 1} 章。")
        except Exception:
            pass

    selected: dict[str, Any] = {}
    if select_spec:
        try:
            source_type, version = _parse_select_spec(select_spec)
            selected = select_version(chapter_id, source_type, version)
        except Exception as exc:
            return _failed("compare-drafts", f"选择版本失败：{exc}")
    if not selected and isinstance(versions.get("selected"), dict):
        selected = versions.get("selected", {})

    if not versions.get("drafts") and not versions.get("edited") and not versions.get("manual") and not committed:
        warnings.append("当前章还没有可比较的草稿或编辑版本。")
    return _success(
        "compare-drafts",
        "版本列表已生成。",
        outputs={
            "chapter_id": chapter_id,
            "drafts": versions.get("drafts", []),
            "edited": versions.get("edited", []),
            "manual": versions.get("manual", []),
            "committed": committed,
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
    committed_chapter: int | None = None,
    allow_refinement: bool = True,
) -> dict[str, Any]:
    paths = _paths()
    if not paths["next_chapter_plan"].exists():
        return _failed("quality-check", "缺少 data/next_chapter_plan.json，请先运行 python main.py plan-next。")
    chapter_plan = load_json(str(paths["next_chapter_plan"]))
    chapter_id = int(chapter_plan.get("chapter_id", 1) or 1)
    source_infos = _resolve_quality_sources(chapter_id, all_versions, draft_version, edited_version, manual_version, committed_chapter)
    if not source_infos:
        return _failed("quality-check", "未找到可评估的当前章版本，请先运行 write-draft 或 edit-draft。")

    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    state = load_json(str(paths["state"])) if paths["state"].exists() else {}
    reports: list[dict[str, Any]] = []
    refinements: list[dict[str, Any]] = []
    for source_info in source_infos:
        source_type = str(source_info.get("source_type", ""))
        source_version = int(source_info.get("version", 0) or 0)
        source_path = str(source_info.get("json_path", ""))
        if source_type == "committed":
            source = {
                "chapter_id": int(source_info.get("chapter_id", source_version) or source_version),
                "chapter_title": str(source_info.get("chapter_title", "")),
                "draft_text": Path(source_path).read_text(encoding="utf-8"),
                "generation": {"mode": "committed", "model": "", "fallback_used": False},
            }
        else:
            source = read_version_payload(source_info) if source_info.get("version") else load_json(source_path)
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

        # ── quality-driven LLM refinement ──────────────────────────
        refinement: dict[str, Any] | None = None
        flags = report.get("flags", [])
        suggestions = report.get("suggestions", [])
        # Quality assessment must remain deterministic and non-blocking by
        # default.  AI refinement is an explicit opt-in workflow, never an
        # implicit follow-up to a normal quality check.
        auto_refine = source_type != "committed" and allow_refinement and bool(getattr(config, "AUTO_REFINE_AFTER_QUALITY", False))
        if auto_refine and (flags or suggestions) and report.get("overall_score", 1.0) is not None:
            try:
                from core.draft_editor_refine import refine_draft_with_quality_report
                from core.draft_writer import _extract_title_from_text

                working_ctx = _load_optional_context(paths)

                refined = refine_draft_with_quality_report(
                    draft=source,
                    chapter_plan=chapter_plan,
                    story_spec=story_spec,
                    blueprint=load_json(str(paths["blueprint"])) if paths["blueprint"].exists() else {},
                    characters=characters,
                    world_bible=world_bible,
                    state=state,
                    quality_report=report,
                    working_context=working_ctx,
                )
                # Extract real title from refined text
                refined_text = refined.get("edited_text", "")
                real_title = _extract_title_from_text(refined_text)
                if real_title:
                    refined["chapter_title"] = real_title
                # Save the refined text as a new edited version
                from system.version_manager import (
                    build_versioned_paths,
                    get_next_version_number,
                    load_versions_index,
                    save_versions_index,
                )
                from core.draft_editor import render_edited_markdown

                refined["source_draft_version"] = source_version
                edit_version = get_next_version_number(chapter_id, "edited")
                vp = build_versioned_paths(chapter_id, "edited", edit_version)
                refined["version"] = edit_version
                refined["version_label"] = f"edited_v{edit_version:03d}"
                context = get_project_context()
                VersionWriterFacade(context).write_legacy_work_version(
                    project=ProjectRef.from_context(context), chapter_id=chapter_id, kind="edited", version=edit_version,
                    payload=refined, markdown=render_edited_markdown(refined),
                    operation_id=f"refined-edited-{chapter_id}-{edit_version}-{HashGuard.sha256_json(refined)[:12]}", select=False,
                )
                versions = load_versions_index(chapter_id)
                save_versions_index(chapter_id, versions)

                # Re-run quality check on the refined version
                refined_report = build_quality_report(
                    refined,
                    "edited",
                    edit_version,
                    vp["json_path"],
                    chapter_plan,
                    story_spec,
                    characters,
                    world_bible,
                    state,
                    use_llm=bool(getattr(config, "USE_DEEPSEEK_FOR_QUALITY_CHECK", False)),
                )
                rj, rm = save_quality_report(refined_report)
                # Update the versions index with the new score
                for ev in versions.get("edited", []):
                    if ev.get("version") == edit_version:
                        ev["quality_score"] = refined_report.get("overall_score")
                        break
                save_versions_index(chapter_id, versions)

                refinement = {
                    "source_type": "edited",
                    "version": edit_version,
                    "version_label": f"edited_v{edit_version:03d}",
                    "issues_fixed": len(flags),
                    "suggestions_applied": len(suggestions),
                    "new_quality_score": refined_report.get("overall_score"),
                    "new_flags": len(refined_report.get("flags", [])),
                    "quality_report_path": rm,
                }
                refinements.append(refinement)
            except Exception as exc:
                refinements.append({"error": _error_text(exc)})

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
    refinement_msg = ""
    if refinements and not any("error" in r for r in refinements):
        refinement_msg = f"；已根据质量报告生成 {len(refinements)} 个修复版本"
    return _success(
        "quality-check",
        f"质量评估完成{refinement_msg}。",
        outputs={
            "chapter_id": chapter_id,
            "reports": reports,
            "report": first,
            "report_count": len(reports),
            "refinements": refinements,
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

    context = get_project_context()
    commit_service = ChapterCommitService(context)
    result = commit_service.commit_chapter(chapter_id, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    if result.status == "failed":
        return _failed("commit-chapter", "\n".join(result.warnings))

    if result.status == "already_committed":
        return _success(
            "commit-chapter",
            "当前章已提交，内容未变化。",
            outputs={
                "chapter_id": result.chapter_id,
                "chapter_path": result.chapter_path,
                "summary_path": result.summary_path,
                "commit_id": result.commit_id,
                "canon_revision_id": result.canon_revision_id,
            },
            warnings=result.warnings,
        )

    warnings = list(result.warnings)
    for key, value in result.post_commit.items():
        if value != "success":
            warnings.append(f"{key}: {value}")

    state = load_json(str(paths["state"]))
    context_json_path = ""
    context_markdown_path = ""
    try:
        context_data, context_json_path, context_markdown_path = _refresh_current_context_after_commit(paths, state)
        state["context"] = {
            "created": True,
            "json_path": context_json_path,
            "markdown_path": context_markdown_path,
            "recent_raw_chapters": 3,
            "older_chapters_strategy": "summary_only",
        }
        save_json(str(paths["state"]), state)
        warnings.extend(context_data.get("warnings", []))
    except Exception as exc:
        warnings.append(f"Writing context refresh failed; run build-context to retry: {str(exc)[:160]}")
    reflection_job = None
    try:
        from system.job_manager import get_job_manager
        reflection_job = get_job_manager().create_job("chapter_reflection", {"chapter_id": chapter_id, "created_by": "system"}, context=context)
    except Exception as exc:
        warnings.append(f"创作复盘待重试：{str(exc)[:160]}")
    try:
        from planning_engine.rolling_integration import mark_anchor_changed
        rolling_notice = mark_anchor_changed(context, "canon_commit")
        if rolling_notice.get("warning") and rolling_notice.get("changed"):
            warnings.append(str(rolling_notice["warning"]))
    except Exception as exc:
        warnings.append(f"Rolling window status check can be retried manually: {str(exc)[:160]}")

    return _success(
        "commit-chapter",
        "当前章已提交。",
        outputs={
            "chapter_id": result.chapter_id,
            "chapter_path": result.chapter_path,
            "summary_path": result.summary_path,
            "commit_id": result.commit_id,
            "canon_revision_id": result.canon_revision_id,
            "source_type": result.source_type.value,
            "source_version_id": result.source_version_id,
            "source_hash": result.source_hash,
            "source_used": result.source_type.value,
            "source_version": _extract_version_number(result.source_version_id),
            "source_path": result.source_path,
            "context_json_path": context_json_path,
            "context_markdown_path": context_markdown_path,
            "creative_reflection_job_id": reflection_job.get("job_id") if reflection_job else None,
        },
        warnings=warnings,
    )


def sync_obsidian_command(dry_run: bool = False, prune_stale: bool = False) -> dict[str, Any]:
    paths = _paths()
    if not paths["story_spec"].exists():
        return _failed("sync-obsidian", "缺少 data/story_spec.json。")

    from system.obsidian_binding_service import ObsidianBindingService, ObsidianBindingNotFound, ObsidianBindingInvalid
    from core.project import resolve_workspace_root

    context = get_project_context()
    workspace_root = resolve_workspace_root(context.root)

    try:
        service = ObsidianBindingService(workspace_root)
        result = service.sync(context.root.name, "main", context.data_dir, dry_run=dry_run, prune_stale=prune_stale)
        msg = "Obsidian 同步预览完成。" if dry_run else "Obsidian 同步完成。"
        return _success("sync-obsidian", msg, outputs=result, warnings=[])
    except ObsidianBindingNotFound:
        return {**_failed("sync-obsidian", "项目未绑定到 Obsidian Vault，请先运行 obsidian-bind 命令。"), "code": "OBSIDIAN_NOT_BOUND"}
    except ObsidianBindingInvalid as e:
        return {**_failed("sync-obsidian", str(e)), "code": "OBSIDIAN_BINDING_INVALID"}
    except Exception as e:
        return _failed("sync-obsidian", f"同步失败：{str(e)}")


def pull_obsidian_command(
    file: str | None = None,
    expected_hash: str | None = None,
    apply: bool = False,
    repair_converged: bool = False,
) -> dict[str, Any]:
    from system.obsidian_binding_service import (
        ObsidianBindingService,
        ObsidianBindingInvalid,
        ObsidianBindingNotFound,
    )
    from system.obsidian_pull_service import (
        ObsidianPullConflict,
        ObsidianPullInvalid,
        ObsidianPullNotFound,
        ObsidianPullService,
        ObsidianPullStalePreview,
        ObsidianPullUnsafe,
    )

    try:
        project_root = resolve_current_project_root()
        if project_root is None:
            return {**_failed("pull-obsidian", "无法解析当前项目根目录。"), "code": "PROJECT_ROOT_NOT_FOUND"}
        workspace_root = resolve_workspace_root(project_root)
        binding_service = ObsidianBindingService(workspace_root)
        context = get_project_context()
        binding = binding_service.get_binding(context.root.name, "main")
        if binding is None:
            return {**_failed("pull-obsidian", "当前项目未绑定 Obsidian。"), "code": "OBSIDIAN_NOT_BOUND"}
        pull_service = ObsidianPullService(binding, context)

        if repair_converged:
            plan = pull_service.repair_converged()
            return _success(
                "pull-obsidian",
                f"修复了 {plan.summary['converged']} 个 converged 项。",
                outputs={"status": "repaired", "summary": plan.summary},
            )

        if file:
            if apply:
                if not expected_hash:
                    return {**_failed("pull-obsidian", "--apply 必须同时提供 --expected-hash。"), "code": "MISSING_EXPECTED_HASH"}
                result = pull_service.import_file(file, expected_hash)
                if result.status in ("failed", "rejected", "stale_preview", "commit_failed"):
                    return {**_failed("pull-obsidian", result.error or "导入失败"), "code": result.status.upper()}
                return _success(
                    "pull-obsidian",
                    f"已导入 {file}。",
                    outputs={"status": result.status, **result.to_dict()},
                    warnings=result.warnings,
                )
            else:
                preview = pull_service.preview_file(file)
                return _success(
                    "pull-obsidian",
                    f"预览 {file}。",
                    outputs={"status": "preview", **preview.to_dict()},
                )

        plan = pull_service.scan()
        return _success(
            "pull-obsidian",
            f"扫描完成，共 {len(plan.entries)} 个文件。",
            outputs={"status": "scan", **plan.to_dict()},
        )
    except ObsidianBindingNotFound:
        return {**_failed("pull-obsidian", "当前项目未绑定 Obsidian。"), "code": "OBSIDIAN_NOT_BOUND"}
    except (ObsidianBindingInvalid, ObsidianPullInvalid) as e:
        return {**_failed("pull-obsidian", str(e)), "code": "OBSIDIAN_BINDING_INVALID"}
    except ObsidianPullUnsafe as e:
        return {**_failed("pull-obsidian", str(e)), "code": "OBSIDIAN_PATH_UNSAFE"}
    except ObsidianPullNotFound as e:
        return {**_failed("pull-obsidian", str(e)), "code": "OBSIDIAN_PULL_NOT_FOUND"}
    except ObsidianPullStalePreview as e:
        return {**_failed("pull-obsidian", str(e)), "code": "OBSIDIAN_IMPORT_STALE_PREVIEW"}
    except ObsidianPullConflict as e:
        return {**_failed("pull-obsidian", str(e)), "code": "OBSIDIAN_PULL_CONFLICT"}
    except Exception as e:
        return _failed("pull-obsidian", f"回导失败：{str(e)}")


def index_vault_command() -> dict[str, Any]:
    from system.vector_index_lifecycle import rebuild_project_index

    result = rebuild_project_index(get_project_context(), timeline_id="main")
    if result.get("status") == "failed":
        return _failed("index-vault", result.get("message", "向量索引构建失败。"))
    return _success(
        "index-vault",
        result.get("message", "向量索引已更新。"),
        outputs=result.get("outputs", {}),
        warnings=result.get("warnings", []),
    )


def repair_current_quality_report_command(chapter_id: int | None = None, force: bool = False) -> dict[str, Any]:
    """Queue a Lite report for the active canon only; never for a selected draft."""
    from system.job_manager import get_job_manager
    from system.memory_repair_service import MemoryRepairService
    from system.revision_service import RevisionService

    context = get_project_context()
    service = MemoryRepairService(context)
    status = service.quality_status(chapter_id)
    candidates = [item for item in status.get("items", []) if item.get("status") in {"missing", "stale", "failed", "generating"}]
    if not candidates:
        return _success("repair-quality-report", "\u5f53\u524d\u6b63\u53f2\u5df2\u6709\u6709\u6548\u8d28\u91cf\u62a5\u544a\uff0c\u65e0\u9700\u91cd\u590d\u751f\u6210\u3002", outputs={"status": status})
    selected_items = candidates if chapter_id is None else candidates[:1]
    jobs: list[dict[str, Any]] = []
    for selected in selected_items:
        if selected.get("status") == "generating":
            continue
        canon = RevisionService(context).active_canon(int(selected["chapter_id"]))
        jobs.append(get_job_manager().create_job(
            "generate_quality_report",
            {
                "chapter_id": int(selected["chapter_id"]),
                "canon_version_id": canon["canon_version_id"],
                "content_hash": canon["content_hash"],
                "analysis_profile": "lite",
                "force": bool(force),
                "created_by": "user",
            },
            context=context,
        ))
    if not jobs:
        return _success("repair-quality-report", "\u5f53\u524d\u6b63\u53f2\u8d28\u91cf\u62a5\u544a\u6b63\u5728\u751f\u6210\u3002", outputs={"status": status})
    return _success("repair-quality-report", "\u5df2\u521b\u5efa\u5f53\u524d\u6b63\u53f2\u8d28\u91cf\u62a5\u544a\u4efb\u52a1\u3002", outputs={"job": jobs[0], "jobs": jobs, "status": status, "chapter_ids": [int(item["chapter_id"]) for item in selected_items]})


def initialize_vector_index_command(rebuild: bool = False) -> dict[str, Any]:
    """Queue a project-local vector-index repair with no remote dependency."""
    from system.job_manager import get_job_manager
    from system.memory_repair_service import MemoryRepairService

    context = get_project_context()
    status = MemoryRepairService(context).vector_status()
    if status.get("status") in {"ready", "empty"} and not rebuild:
        return _success("initialize-vector-index", "\u672c\u5730\u5411\u91cf\u7d22\u5f15\u5df2\u53ef\u7528\uff0c\u65e0\u9700\u91cd\u590d\u521d\u59cb\u5316\u3002", outputs={"status": status})
    job_type = "rebuild_vector_index" if rebuild else ("incremental_vector_index" if status.get("status") == "stale" else "initialize_vector_index")
    job = get_job_manager().create_job(
        job_type,
        {"created_by": "user", "source_snapshot": status.get("source_snapshot", {}), "mode": "rebuild" if rebuild else "initialize"},
        context=context,
    )
    return _success("initialize-vector-index", "\u5df2\u521b\u5efa\u672c\u5730\u5411\u91cf\u7d22\u5f15\u4efb\u52a1\u3002", outputs={"job": job, "status": status})



def simulate_reader_command(chapter: int | None = None, version_id: str | None = None) -> dict[str, Any]:
    from core.project_context import get_project_context
    from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
    from system.reader_simulator import ReaderSimulatorService, ReaderSimulatorError
    from system.reader_simulation_store import ReaderSimulationStore

    try:
        context = get_project_context()
        if chapter is None:
            return _failed("simulate-reader", "必须指定 --chapter 参数。")

        state_path = context.data_dir / "state.json"
        state = load_json(str(state_path)) if state_path.exists() else {}
        project_id = state.get("project_id", "default-project")
        timeline_id = state.get("timeline_id", "main")

        request = ReaderSimulationRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=chapter,
            source_version_id=version_id,
            mode=SimulationMode.RULE,
        )
        simulator = ReaderSimulatorService(context)
        run = simulator.run_simulation(request)

        store = ReaderSimulationStore(context)
        store_path = store.save_run(run)

        if run.status.value == "failed":
            return _failed("simulate-reader", run.error or "模拟失败。")

        result = run.result
        return _success(
            "simulate-reader",
            f"第{chapter}章读者模拟完成。",
            outputs={
                "run_id": run.run_id,
                "chapter_id": chapter,
                "source_version_id": run.snapshot.source.source_version_id,
                "engagement_score": result.engagement_score.score if result else 0.0,
                "retention_risk": result.retention_risk.score if result else 0.0,
                "evaluator_version": result.evaluator_version if result else "",
            },
        )
    except ReaderSimulatorError as exc:
        return _failed("simulate-reader", exc.message, code=exc.code)
    except Exception as exc:
        return _failed("simulate-reader", str(exc))


def list_reader_simulations_command(chapter: int | None = None) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.reader_simulation_store import ReaderSimulationStore

    try:
        context = get_project_context()
        store = ReaderSimulationStore(context)
        runs = store.list_runs(chapter_id=chapter)

        outputs = []
        for run in runs:
            outputs.append({
                "run_id": run.run_id,
                "chapter_id": run.request.chapter_id,
                "source_version_id": run.snapshot.source.source_version_id,
                "status": run.status.value,
                "created_at": run.created_at.isoformat(),
                "engagement_score": run.result.engagement_score.score if run.result else None,
                "retention_risk": run.result.retention_risk.score if run.result else None,
            })

        return _success(
            "list-reader-simulations",
            f"共找到 {len(outputs)} 条读者模拟记录。",
            outputs={"simulations": outputs},
        )
    except Exception as exc:
        return _failed("list-reader-simulations", str(exc))


def show_reader_simulation_command(run_id: str) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.reader_simulation_store import ReaderSimulationStore

    try:
        context = get_project_context()
        store = ReaderSimulationStore(context)
        run = store.load_run(run_id)

        if run is None:
            return _failed("show-reader-simulation", f"未找到 run_id: {run_id}")

        staleness = store.check_run_staleness(run_id)
        result_state = staleness.state.value
        stale_reasons = [r.value for r in staleness.stale_reasons]

        result = {}
        if run.result:
            result = {
                "engagement_score": {
                    "score": run.result.engagement_score.score,
                    "level": run.result.engagement_score.level,
                    "reasons": run.result.engagement_score.reasons,
                    "evidence": run.result.engagement_score.evidence,
                },
                "retention_risk": {
                    "score": run.result.retention_risk.score,
                    "level": run.result.retention_risk.level.value,
                    "risk_points": run.result.retention_risk.risk_points,
                },
                "reader_emotion_curve": [
                    {
                        "position": node.position,
                        "segment_label": node.segment_label,
                        "tension": node.tension,
                        "curiosity": node.curiosity,
                        "emotional_intensity": node.emotional_intensity,
                        "payoff": node.payoff,
                    }
                    for node in run.result.reader_emotion_curve
                ],
                "problem_flags": [
                    {
                        "code": flag.code,
                        "severity": flag.severity.value,
                        "category": flag.category.value,
                        "message": flag.message,
                    }
                    for flag in run.result.problem_flags
                ],
                "optimization_suggestions": [
                    {
                        "priority": s.priority,
                        "target": s.target,
                        "reason": s.reason,
                        "expected_effect": s.expected_effect,
                    }
                    for s in run.result.optimization_suggestions
                ],
                "novel_health": {
                    "overall_score": run.result.novel_health.overall_score,
                    "pacing": run.result.novel_health.pacing,
                    "clarity": run.result.novel_health.clarity,
                    "continuity": run.result.novel_health.continuity,
                    "conflict": run.result.novel_health.conflict,
                    "payoff": run.result.novel_health.payoff,
                    "style_stability": run.result.novel_health.style_stability,
                    "warnings": run.result.novel_health.warnings,
                },
                "evaluator_version": run.result.evaluator_version,
                "evaluated_at": run.result.evaluated_at.isoformat(),
            }

        return _success(
            "show-reader-simulation",
            f"读者模拟详情 (状态: {result_state})",
            outputs={
                "run_id": run.run_id,
                "status": run.status.value,
                "result_state": result_state,
                "stale_reasons": stale_reasons,
                "chapter_id": run.snapshot.chapter_id,
                "project_id": run.snapshot.project_id,
                "timeline_id": run.snapshot.timeline_id,
                "source": {
                    "source_version_id": run.snapshot.source.source_version_id,
                    "source_type": run.snapshot.source.source_type,
                    "source_hash": run.snapshot.source.source_hash,
                    "title": run.snapshot.source.title,
                    "character_count": run.snapshot.source.character_count,
                },
                "result": result,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "warnings": run.warnings,
                "error": run.error,
            },
        )
    except Exception as exc:
        return _failed("show-reader-simulation", str(exc))


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

    report = run_memory_health_check(get_project_context().data_dir, full=full)
    paths = save_memory_health_report(report, get_project_context().data_dir)
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


def run_chapter_command(auto_commit: bool = False, require_model: bool = False) -> dict[str, Any]:
    from system.pipeline_runner import run_single_chapter_pipeline

    report = run_single_chapter_pipeline(auto_commit=auto_commit, require_model=require_model)
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

def _write_model_config_error() -> str:
    provider = str(getattr(config, "LLM_PROVIDER", "") or "").strip().lower()
    if provider in {"mock", "local", "ollama", "ollama_cloud"}:
        return "?????????? API ?????? .env ??? LLM_PROVIDER=api?"
    api_key = str(
        getattr(config, "WRITE_MODEL_API_KEY", "")
        or getattr(config, "MODEL_API_KEY", "")
        or getattr(config, "OPENAI_API_KEY", "")
        or getattr(config, "DEEPSEEK_API_KEY", "")
        or ""
    ).strip()
    base_url = str(
        getattr(config, "WRITE_MODEL_BASE_URL", "")
        or getattr(config, "MODEL_BASE_URL", "")
        or getattr(config, "OPENAI_API_BASE", "")
        or getattr(config, "OPENAI_BASE_URL", "")
        or getattr(config, "DEEPSEEK_BASE_URL", "")
        or ""
    ).strip()
    model = str(
        getattr(config, "WRITE_MODEL_NAME", "")
        or getattr(config, "MODEL_NAME", "")
        or getattr(config, "OPENAI_MODEL", "")
        or getattr(config, "DEEPSEEK_MODEL", "")
        or ""
    ).strip()
    if not api_key:
        return "?? WRITE_MODEL_API_KEY??? .env ?????????? API Key?"
    if not base_url:
        return "?? WRITE_MODEL_BASE_URL??? .env ???????????????"
    if not model:
        return "?? WRITE_MODEL_NAME??? .env ??????????????"
    return ""
def draft_paths(chapter_id: int, context=None) -> tuple[Path, Path]:
    ctx = context if context is not None else get_project_context()
    file_stem = f"chapter_{chapter_id:03d}_draft"
    return ctx.drafts_dir / f"{file_stem}.json", ctx.drafts_dir / f"{file_stem}.md"


def edited_paths(chapter_id: int, context=None) -> tuple[Path, Path]:
    ctx = context if context is not None else get_project_context()
    file_stem = f"chapter_{chapter_id:03d}_edited"
    return ctx.edited_dir / f"{file_stem}.json", ctx.edited_dir / f"{file_stem}.md"


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
    if not isinstance(version_paths["json_path"], (str, Path)):
        # Test-only in-memory compatibility fixture; it never reaches a file.
        save_json(version_paths["json_path"], draft); save_markdown(version_paths["markdown_path"], markdown)
        save_json(str(latest_json_path), draft); save_markdown(str(latest_markdown_path), markdown)
        save_versions_index(chapter_id, load_versions_index(chapter_id))
    else:
        context = get_project_context()
        VersionWriterFacade(context).write_legacy_work_version(
            project=ProjectRef.from_context(context), chapter_id=chapter_id, kind="draft", version=version,
            payload=draft, markdown=markdown,
            operation_id=f"draft-write-{chapter_id}-{version}-{HashGuard.sha256_json(draft)[:12]}", select=False,
            aliases={latest_json_path.as_posix(): "", latest_markdown_path.as_posix(): markdown},
        )
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
    save_json(str(_paths()["state"]), state)
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
    if not isinstance(version_paths["json_path"], (str, Path)):
        save_json(version_paths["json_path"], edited); save_markdown(version_paths["markdown_path"], markdown)
        save_json(str(latest_json_path), edited); save_markdown(str(latest_markdown_path), markdown)
        save_versions_index(chapter_id, load_versions_index(chapter_id))
    else:
        context = get_project_context()
        VersionWriterFacade(context).write_legacy_work_version(
            project=ProjectRef.from_context(context), chapter_id=chapter_id, kind="edited", version=version,
            payload=edited, markdown=markdown,
            operation_id=f"edited-write-{chapter_id}-{version}-{HashGuard.sha256_json(edited)[:12]}", select=False,
            aliases={latest_json_path.as_posix(): "", latest_markdown_path.as_posix(): markdown},
        )
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
    save_json(str(_paths()["state"]), state)
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
    committed_chapter: int | None = None,
) -> list[dict[str, Any]]:
    if committed_chapter is not None:
        ctx = get_project_context()
        chapter_path = ctx.chapters_dir / f"chapter_{int(committed_chapter):03d}.md"
        if not chapter_path.exists():
            return []
        chapter_text = chapter_path.read_text(encoding="utf-8")
        title = chapter_text.splitlines()[0].lstrip("#").strip() if chapter_text.strip() else ""
        return [{
            "chapter_id": int(committed_chapter),
            "chapter_title": title,
            "source_type": "committed",
            "version": int(committed_chapter),
            "version_label": f"chapter_{int(committed_chapter):03d}",
            "json_path": chapter_path.as_posix(),
            "markdown_path": chapter_path.as_posix(),
        }]
    versions = load_versions_index(chapter_id)
    if all_versions:
        return list(versions.get("drafts", [])) + list(versions.get("edited", [])) + list(versions.get("manual", []))
    if draft_version is not None:
        return [_find_version_info(versions, "draft", draft_version)] if _find_version_info(versions, "draft", draft_version) else []
    if edited_version is not None:
        return [_find_version_info(versions, "edited", edited_version)] if _find_version_info(versions, "edited", edited_version) else []
    if manual_version is not None:
        return [_find_version_info(versions, "manual", manual_version)] if _find_version_info(versions, "manual", manual_version) else []
    # Default: always prefer Edited (AI-polished) version
    if versions.get("edited"):
        return [versions["edited"][-1]]
    if versions.get("manual"):
        return [versions["manual"][-1]]
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
    raw_selected = _raw_selected_version(chapter_id)
    versions = load_versions_index(chapter_id)
    selected = versions.get("selected", {})
    if raw_selected and not selected:
        warnings.append("选中版本不存在，已回退到最新可用版本。")
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


def _raw_selected_version(chapter_id: int, context=None) -> dict[str, Any]:
    ctx = context if context is not None else get_project_context()
    path = ctx.versions_dir / f"chapter_{chapter_id:03d}_versions.json"
    if not path.exists():
        return {}
    try:
        payload = load_json(str(path))
    except (PermissionError, FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    selected = payload.get("selected", {}) if isinstance(payload, dict) else {}
    return selected if isinstance(selected, dict) else {}


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


def _paths(project_root: Path | None = None) -> dict[str, Path]:
    root = get_project_context(project_root).root
    return {
        "story_spec": root / "data" / "story_spec.json",
        "state": root / "data" / "state.json",
        "blueprint": root / "data" / "story_blueprint.json",
        "characters": root / "data" / "characters.json",
        "world_bible": root / "data" / "world_bible.json",
        "next_chapter_plan": root / "data" / "next_chapter_plan.json",
        "memory_index": root / "data" / "memory" / "memory_index.json",
        "current_context": root / "data" / "context" / "current_context.json",
    }


def _missing_plan_next_inputs(paths: dict[str, Path]) -> str:
    if not paths["story_spec"].exists():
        return "缺少 data/story_spec.json。"
    if not paths["blueprint"].exists():
        return "story_blueprint.json 自动修复失败，请检查 logs/generation.log。"
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


def _load_or_create_state(story_spec: dict[str, Any], context=None) -> dict[str, Any]:
    ctx = context if context is not None else get_project_context()
    state_path = ctx.data_dir / "state.json"
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


def _error_text(exc: BaseException) -> str:
    msg = str(exc).strip()
    return msg[:300] if msg else exc.__class__.__name__


def _failed(name: str, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "failed",
        "message": message,
        "outputs": {},
        "warnings": [],
    }


def _scan_committed_chapters(data_dir: Path) -> list[dict[str, Any]]:
    """Return metadata for all committed chapter files under *data_dir*/chapters/."""
    chapters_dir = data_dir / "chapters"
    if not chapters_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for md_path in sorted(chapters_dir.glob("chapter_*.md")):
        import re

        m = re.search(r"chapter_(\d+)", md_path.stem)
        chapter_id = int(m.group(1)) if m else 0
        text = md_path.read_text(encoding="utf-8")
        word_count = len([c for c in text if not c.isspace()])
        from core.draft_writer import _extract_title_from_text
        title = _extract_title_from_text(text)
        entries.append({
            "source_type": "committed",
            "version": chapter_id,
            "version_label": f"chapter_{chapter_id:03d}",
            "chapter_id": chapter_id,
            "chapter_title": title,
            "json_path": md_path.as_posix(),
            "markdown_path": md_path.as_posix(),
            "actual_word_count": word_count,
            "mode": "committed",
            "quality_score": None,
        })
    return entries


def clone_project_command(
    source_project_id: str,
    target_name: str,
    target_slug: str | None = None,
) -> dict[str, Any]:
    """Clone an existing project into an independent new project."""
    from core.project import resolve_workspace_root

    workspace_root = resolve_workspace_root()
    manager = get_project_manager(workspace_root)

    try:
        result = manager.clone_project(source_project_id, target_name, target_slug)
    except ProjectManagerError as exc:
        return _failed("clone-project", str(exc))

    return _success(
        "clone-project",
        f"项目已克隆为「{target_name}」。",
        outputs=result,
        warnings=result.get("warnings", []),
    )


def obsidian_bind_command(
    project_id: str,
    vault_root: str,
    target_relative_path: str,
    timeline_id: str = "main",
    adopt_existing: bool = False,
) -> dict[str, Any]:
    """Bind a project to an Obsidian vault target."""
    from system.obsidian_binding_service import (
        ObsidianBindingService,
        ObsidianBindingConflict,
        ObsidianBindingInvalid,
        ObsidianMarkerMismatch,
        ObsidianTargetUnsafe,
    )
    from core.project import resolve_workspace_root

    workspace_root = resolve_workspace_root()
    service = ObsidianBindingService(workspace_root)

    try:
        binding = service.bind(
            project_id=project_id,
            timeline_id=timeline_id,
            vault_root=Path(vault_root),
            target_relative_path=target_relative_path,
            adopt_existing=adopt_existing,
        )
        return _success(
            "obsidian-bind",
            f"项目已绑定到 Obsidian Vault。",
            outputs={
                "binding_id": binding.binding_id,
                "project_id": binding.project_id,
                "timeline_id": binding.timeline_id,
                "vault_root": binding.vault_root.as_posix(),
                "target_relative_path": binding.target_relative_path,
                "target_full_path": binding.target_full_path.as_posix(),
                "status": binding.status.value,
                "created_at": binding.created_at.isoformat(),
            },
        )
    except ObsidianTargetUnsafe as e:
        return _failed("obsidian-bind", str(e), code="TARGET_UNSAFE")
    except ObsidianBindingConflict as e:
        return _failed("obsidian-bind", str(e), code="BINDING_CONFLICT")
    except ObsidianMarkerMismatch as e:
        return _failed("obsidian-bind", str(e), code="MARKER_MISMATCH")
    except Exception as e:
        return _failed("obsidian-bind", f"绑定失败：{str(e)}")


def obsidian_status_command(project_id: str, timeline_id: str = "main") -> dict[str, Any]:
    """Get Obsidian binding status for a project."""
    from system.obsidian_binding_service import ObsidianBindingService
    from core.project import resolve_workspace_root

    workspace_root = resolve_workspace_root()
    service = ObsidianBindingService(workspace_root)

    status = service.status(project_id, timeline_id)
    return _success("obsidian-status", "", outputs=status)


def obsidian_unbind_command(project_id: str, timeline_id: str = "main") -> dict[str, Any]:
    """Unbind a project from its Obsidian vault."""
    from system.obsidian_binding_service import ObsidianBindingService
    from core.project import resolve_workspace_root

    workspace_root = resolve_workspace_root()
    service = ObsidianBindingService(workspace_root)

    result = service.unbind(project_id, timeline_id)
    if result["deleted"]:
        return _success("obsidian-unbind", "项目已取消绑定。")
    if result["reason"] == "NOT_FOUND":
        return _failed("obsidian-unbind", "未找到绑定记录。")
    if result["reason"].startswith("FOREIGN_MARKER"):
        return _failed("obsidian-unbind", "目标目录存在其他项目的标记，无法解绑。", code="MARKER_MISMATCH")
    if result["reason"] == "MARKER_DELETE_FAILED":
        return _failed("obsidian-unbind", "标记文件删除失败。", code="MARKER_DELETE_FAILED")
    return _failed("obsidian-unbind", "解绑失败。")


def list_reader_personas_command(project_root: Path | None = None) -> dict[str, Any]:
    from system.reader_persona_registry import ReaderPersonaRegistry

    try:
        registry = ReaderPersonaRegistry()
        personas = registry.list_personas()

        persona_list = []
        for persona in personas:
            persona_list.append({
                "persona_id": persona.persona_id,
                "display_name": persona.display_name,
                "description": persona.description,
                "archetype": persona.archetype.value,
                "persona_version": persona.persona_version,
                "enabled": persona.enabled,
            })

        return _success(
            "list-reader-personas",
            f"已加载 {len(persona_list)} 个读者角色",
            outputs={
                "personas": persona_list,
            },
        )
    except Exception as exc:
        return _failed("list-reader-personas", str(exc))


def run_reader_panel_command(
    chapter: int,
    personas: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    from core.project_context import get_project_context
    from core.contracts.reader_persona import PanelMode, ReaderPanelRequest
    from system.reader_panel_service import ReaderPanelService

    try:
        context = get_project_context(project_root)
        service = ReaderPanelService(context)

        persona_ids = [p.strip() for p in personas.split(",") if p.strip()]

        state_path = context.data_dir / "state.json"
        project_id = "unknown"
        timeline_id = "main"
        if state_path.exists():
            import json
            state = json.loads(state_path.read_text(encoding="utf-8"))
            project_id = state.get("project_id", "unknown")
            timeline_id = state.get("timeline_id", "main")

        request = ReaderPanelRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=chapter,
            persona_ids=persona_ids,
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)

        if run.status.value == "failed":
            return _failed("run-reader-panel", run.error or "Panel 运行失败")

        return _success(
            "run-reader-panel",
            f"第{chapter}章读者面板模拟完成",
            outputs={
                "panel_run_id": run.panel_run_id,
                "chapter_id": run.request.chapter_id,
                "persona_count": len(run.request.persona_ids),
                "panel_score": run.result.panel_score if run.result else None,
                "panel_retention_risk": run.result.panel_retention_risk if run.result else None,
                "agreement_level": run.result.agreement.agreement_level.value if run.result else None,
                "status": run.status.value,
            },
        )
    except Exception as exc:
        return _failed("run-reader-panel", str(exc))


def list_reader_panels_command(project_root: Path | None = None) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.reader_panel_store import ReaderPanelStore

    try:
        context = get_project_context(project_root)
        store = ReaderPanelStore(context)
        runs = store.list_runs()

        panel_list = []
        for run in runs:
            staleness = store.check_run_staleness(run.panel_run_id)
            panel_list.append({
                "panel_run_id": run.panel_run_id,
                "chapter_id": run.request.chapter_id,
                "persona_count": len(run.request.persona_ids),
                "status": run.status.value,
                "result_state": staleness.state.value,
                "panel_score": run.result.panel_score if run.result else None,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            })

        return _success(
            "list-reader-panels",
            f"找到 {len(panel_list)} 条读者面板记录",
            outputs={
                "panels": panel_list,
            },
        )
    except Exception as exc:
        return _failed("list-reader-panels", str(exc))


def show_reader_panel_command(
    panel_run_id: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.reader_panel_store import ReaderPanelStore

    try:
        context = get_project_context(project_root)
        store = ReaderPanelStore(context)
        run = store.load_run(panel_run_id)

        if run is None:
            return _failed("show-reader-panel", f"未找到 panel_run_id: {panel_run_id}")

        staleness = store.check_run_staleness(panel_run_id)
        result_state = staleness.state.value
        stale_reasons = [r.value for r in staleness.stale_reasons]

        result = {}
        if run.result:
            persona_results = []
            for pr in run.result.persona_results:
                persona_results.append({
                    "persona_id": pr.persona_id,
                    "engagement_score": pr.engagement_score,
                    "retention_risk": pr.retention_risk,
                    "priority_flags": [
                        {"flag_code": f.flag_code, "severity": f.persona_severity, "priority": f.priority}
                        for f in pr.priority_flags
                    ],
                    "observations": [o.message for o in pr.persona_observations],
                    "optimization_priorities": [o.target for o in pr.optimization_priorities],
                })

            result = {
                "panel_score": run.result.panel_score,
                "panel_retention_risk": run.result.panel_retention_risk,
                "agreement": {
                    "score_spread": run.result.agreement.score_spread,
                    "score_stddev": run.result.agreement.score_stddev,
                    "agreement_level": run.result.agreement.agreement_level.value,
                },
                "disagreements": [
                    {"topic": d.topic, "explanation": d.explanation}
                    for d in run.result.disagreements
                ],
                "consensus_flags": [f.flag_code for f in run.result.consensus_flags],
                "minority_flags": [f.flag_code for f in run.result.minority_flags],
                "panel_suggestions": [
                    {"target": s.target, "priority": s.priority}
                    for s in run.result.panel_suggestions
                ],
                "persona_results": persona_results,
                "panel_evaluator_version": run.result.panel_evaluator_version,
                "persona_set_fingerprint": run.result.persona_set_fingerprint,
            }

        return _success(
            "show-reader-panel",
            f"读者面板详情 (状态: {result_state})",
            outputs={
                "panel_run_id": run.panel_run_id,
                "status": run.status.value,
                "result_state": result_state,
                "stale_reasons": stale_reasons,
                "chapter_id": run.request.chapter_id,
                "project_id": run.request.project_id,
                "timeline_id": run.request.timeline_id,
                "persona_ids": run.request.persona_ids,
                "result": result,
                "base_simulation_run_id": run.base_simulation_run_id,
                "snapshot_id": run.snapshot_id,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "warnings": run.warnings,
                "error": run.error,
            },
        )
    except Exception as exc:
        return _failed("show-reader-panel", str(exc))


def run_reader_persona_model_command(
    chapter: int,
    persona: str,
    mode: str = "mock",
    execution_profile: str = "default",
    allow_model_call: bool = False,
    force: bool = False,
    source_version_id: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    from core.project_context import get_project_context
    from core.contracts.model_persona_execution import (
        ExecutionMode,
        ModelPersonaExecutionRequest,
    )
    from system.model_persona_execution_service import ModelPersonaExecutionService

    try:
        context = get_project_context(project_root)

        state_path = context.data_dir / "state.json"
        project_id = "unknown"
        timeline_id = "main"
        if state_path.exists():
            import json
            state = json.loads(state_path.read_text(encoding="utf-8"))
            project_id = state.get("project_id", "unknown")
            timeline_id = state.get("timeline_id", "main")

        try:
            exec_mode = ExecutionMode(mode)
        except ValueError:
            return _failed("run-reader-persona-model", f"Unknown mode: {mode}")

        request = ModelPersonaExecutionRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=chapter,
            persona_id=persona,
            source_version_id=source_version_id,
            execution_mode=exec_mode,
            execution_profile=execution_profile,
            allow_model_call=allow_model_call,
            force=force,
        )

        service = ModelPersonaExecutionService(context)
        result = service.execute(request)

        outputs = {
            "execution_id": result.execution_id,
            "status": result.status.value,
            "persona_id": result.persona_id,
            "error_code": result.error_code,
            "cache_status": result.cache_status,
            "authoritative_scores": result.authoritative_scores.to_dict(),
        }

        if result.model_feedback:
            outputs["has_feedback"] = True
        if result.usage:
            outputs["usage"] = result.usage.to_dict()
        if result.error:
            outputs["error"] = result.error

        if result.status.value == "blocked":
            outputs["blocked_reason"] = result.error_code or "MODEL_CALL_BLOCKED"
            return _failed("run-reader-persona-model", result.error or "blocked")

        if result.status.value == "failed":
            return _failed("run-reader-persona-model", result.error or "provider failed")

        if result.status.value == "invalid_output":
            return _failed("run-reader-persona-model", result.error or "invalid model output")

        return _success(
            "run-reader-persona-model",
            f"第{chapter}章 {persona} 模型反馈完成 (cache={result.cache_status})",
            outputs=outputs,
        )
    except Exception as exc:
        return _failed("run-reader-persona-model", str(exc))


def list_reader_persona_model_runs_command(
    chapter: int | None = None,
    persona: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.model_persona_execution_service import ModelPersonaExecutionService

    try:
        context = get_project_context(project_root)
        service = ModelPersonaExecutionService(context)
        runs = service.list_runs(chapter_id=chapter, persona_id=persona)

        run_list = []
        for run in runs:
            run_list.append({
                "execution_id": run.execution_id,
                "status": run.status.value,
                "persona_id": run.persona_id,
                "cache_status": run.cache_status,
                "created_at": run.created_at.isoformat(),
            })

        return _success(
            "list-reader-persona-model-runs",
            f"找到 {len(run_list)} 条模型反馈记录",
            outputs={"runs": run_list},
        )
    except Exception as exc:
        return _failed("list-reader-persona-model-runs", str(exc))


def show_reader_persona_model_run_command(
    execution_id: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    from core.project_context import get_project_context
    from system.model_persona_execution_service import ModelPersonaExecutionService

    try:
        context = get_project_context(project_root)
        service = ModelPersonaExecutionService(context)
        run = service.get_run(execution_id)

        if run is None:
            return _failed("show-reader-persona-model-run", f"未找到 execution_id: {execution_id}")

        outputs = {
            "execution_id": run.execution_id,
            "status": run.status.value,
            "persona_id": run.persona_id,
            "persona_version": run.persona_version,
            "source_hash": run.source_hash,
            "context_hash": run.context_hash,
            "reader_evaluator_version": run.reader_evaluator_version,
            "prompt_template_version": run.prompt_template_version,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
            "generation_parameters": run.generation_parameters.to_dict(),
            "input_fingerprint": run.input_fingerprint,
            "authoritative_scores": run.authoritative_scores.to_dict(),
            "cache_status": run.cache_status,
            "usage": run.usage.to_dict() if run.usage else None,
            "warnings": run.warnings,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

        if run.model_feedback:
            outputs["model_feedback"] = {
                "reader_reaction": run.model_feedback.reader_reaction,
                "overall_impression": run.model_feedback.overall_impression,
                "strengths_count": len(run.model_feedback.strengths),
                "concerns_count": len(run.model_feedback.concerns),
                "reader_questions_count": len(run.model_feedback.reader_questions),
                "optimization_directions_count": len(run.model_feedback.optimization_directions),
            }

        if run.grounding_report:
            outputs["grounding_report"] = {
                "valid_reference_count": run.grounding_report.valid_reference_count,
                "invalid_reference_count": run.grounding_report.invalid_reference_count,
                "unsupported_item_count": run.grounding_report.unsupported_item_count,
                "grounding_coverage": run.grounding_report.grounding_coverage,
            }

        return _success(
            "show-reader-persona-model-run",
            f"执行记录: {execution_id}",
            outputs=outputs,
        )
    except Exception as exc:
        return _failed("show-reader-persona-model-run", str(exc))


def _model_persona_panel_request(
    *, chapter: int, personas: list[str], mode: str, execution_profile: str,
    allow_model_call: bool, max_provider_calls: int, force: bool,
    source_version_id: str | None, project_root: Path | None,
):
    import json
    from core.contracts.model_persona_execution import ExecutionMode
    from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest
    context = get_project_context(project_root)
    state_path = context.data_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    return context, ModelPersonaPanelExecutionRequest(
        project_id=state.get("project_id", "default-project"),
        timeline_id=state.get("timeline_id", "main"), chapter_id=chapter,
        persona_ids=personas, source_version_id=source_version_id,
        execution_mode=ExecutionMode(mode), execution_profile=execution_profile,
        allow_model_call=allow_model_call, max_provider_calls=max_provider_calls, force=force,
    )


def plan_reader_persona_model_panel_command(
    chapter: int, personas: list[str], mode: str = "mock", execution_profile: str = "default",
    allow_model_call: bool = False, max_provider_calls: int = 1, force: bool = False,
    source_version_id: str | None = None, project_root: Path | None = None,
) -> dict[str, Any]:
    from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
    try:
        context, request = _model_persona_panel_request(
            chapter=chapter, personas=personas, mode=mode, execution_profile=execution_profile,
            allow_model_call=allow_model_call, max_provider_calls=max_provider_calls,
            force=force, source_version_id=source_version_id, project_root=project_root,
        )
        plan = ModelPersonaPanelExecutionService(context).plan(request)
        return _success("plan-reader-persona-model-panel", "Model persona panel plan created.", outputs={
            "requested_persona_ids": plan.requested_persona_ids, "ordered_persona_ids": plan.ordered_persona_ids,
            "cache_hit_persona_ids": plan.cache_hit_persona_ids, "cache_miss_persona_ids": plan.cache_miss_persona_ids,
            "expected_provider_calls": plan.expected_provider_calls, "max_provider_calls": plan.max_provider_calls,
            "can_execute": plan.can_execute, "blocked_reason": plan.blocked_reason, "error_code": plan.error_code,
        })
    except Exception as exc:
        return _failed("plan-reader-persona-model-panel", str(exc))


def run_reader_persona_model_panel_command(
    chapter: int, personas: list[str], mode: str = "mock", execution_profile: str = "default",
    allow_model_call: bool = False, max_provider_calls: int = 1, force: bool = False,
    source_version_id: str | None = None, project_root: Path | None = None,
) -> dict[str, Any]:
    from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
    try:
        context, request = _model_persona_panel_request(
            chapter=chapter, personas=personas, mode=mode, execution_profile=execution_profile,
            allow_model_call=allow_model_call, max_provider_calls=max_provider_calls,
            force=force, source_version_id=source_version_id, project_root=project_root,
        )
        result = ModelPersonaPanelExecutionService(context).execute(request)
        outputs = _model_persona_panel_outputs(result)
        if result.status.value == "blocked":
            return _failed("run-reader-persona-model-panel", result.error_code or "blocked")
        return _success("run-reader-persona-model-panel", "Model persona panel execution completed.", outputs=outputs)
    except Exception as exc:
        return _failed("run-reader-persona-model-panel", str(exc))


def _model_persona_panel_outputs(run) -> dict[str, Any]:
    return {
        "panel_execution_id": run.panel_execution_id, "status": run.status.value,
        "ordered_persona_ids": run.ordered_persona_ids, "child_execution_ids": run.child_execution_ids,
        "child_statuses": run.child_statuses, "expected_provider_call_count": run.expected_provider_call_count,
        "actual_provider_call_count": run.actual_provider_call_count, "cache_hit_count": run.cache_hit_count,
        "cache_miss_count": run.cache_miss_count, "usage": run.usage.to_dict() if run.usage else None,
        "usage_completeness": run.usage_completeness, "error_code": run.error_code,
        "staleness": run.staleness.value,
    }


def list_reader_persona_model_panel_runs_command(chapter: int | None = None, project_root: Path | None = None) -> dict[str, Any]:
    from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
    try:
        runs = ModelPersonaPanelExecutionService(get_project_context(project_root)).list_runs(chapter)
        return _success("list-reader-persona-model-panel-runs", "Model persona panel runs loaded.", outputs={"runs": [_model_persona_panel_outputs(run) for run in runs]})
    except Exception as exc:
        return _failed("list-reader-persona-model-panel-runs", str(exc))


def show_reader_persona_model_panel_run_command(panel_execution_id: str, project_root: Path | None = None) -> dict[str, Any]:
    from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
    try:
        service = ModelPersonaPanelExecutionService(get_project_context(project_root))
        run = service.get_run(panel_execution_id)
        if run is None:
            return _failed("show-reader-persona-model-panel-run", "PANEL_RUN_NOT_FOUND")
        outputs = _model_persona_panel_outputs(run)
        outputs["staleness"] = service.check_staleness(panel_execution_id).value
        return _success("show-reader-persona-model-panel-run", "Model persona panel run loaded.", outputs=outputs)
    except Exception as exc:
        return _failed("show-reader-persona-model-panel-run", str(exc))


def show_reader_persona_panel_review_command(
    *, chapter: int, source_version_id: str | None = None,
    panel_execution_id: str | None = None, project_root: Path | None = None,
) -> dict[str, Any]:
    """Read-only deterministic panel review query."""
    from system.model_persona_panel_review_service import ModelPersonaPanelReviewService

    try:
        context = get_project_context(project_root)
        review = ModelPersonaPanelReviewService(context).review(
            chapter_id=chapter, source_version_id=source_version_id,
            panel_execution_id=panel_execution_id,
        )
        return _success(
            "show-reader-persona-panel-review",
            "Deterministic reader persona panel review loaded.",
            outputs=review.to_dict(), warnings=review.warnings,
        )
    except Exception as exc:
        code = getattr(exc, "code", None) or str(exc)
        return _failed("show-reader-persona-panel-review", code)
