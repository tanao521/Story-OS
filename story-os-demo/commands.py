from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import config
from config import DATA_DIR
from core.blueprint_generator import generate_blueprint, render_blueprint_markdown
from core.chapter_committer import commit_chapter, render_committed_chapter_markdown
from core.character_builder import generate_characters, render_characters_markdown
from core.draft_editor import edit_draft, render_edited_markdown
from core.draft_writer import render_draft_markdown, write_chapter_draft
from core.next_chapter_planner import plan_next_chapter, render_next_chapter_plan_markdown
from core.project import ensure_project_structure, resolve_current_project_root
from core.project_context import get_project_context
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible, render_world_bible_markdown
from llm.planning_service import (
    create_deepseek_client,
    generate_blueprint_with_deepseek,
    plan_next_chapter_with_deepseek,
    should_use_deepseek_for_planning,
)
from system.context_builder import build_working_context, save_current_context
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


def _refresh_current_context_after_commit(paths: dict[str, Path], state: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Persist a fresh context without changing the commit workflow stage."""
    memory_index = load_json(str(paths["memory_index"]))
    story_spec = load_json(str(paths["story_spec"])) if paths["story_spec"].exists() else {}
    characters = load_json(str(paths["characters"])) if paths["characters"].exists() else {}
    world_bible = load_json(str(paths["world_bible"])) if paths["world_bible"].exists() else {}
    context = build_working_context(state, memory_index, _build_context_query(state, paths), story_spec, characters, world_bible)
    try:
        planning = load_planning(get_project_context())
        current = int(state.get("current_chapter", 0) or 0) + 1
        chapter_plan = next((item for item in planning.get("chapters", []) if int(item.get("chapter_number", item.get("chapter_id", -1)) or -1) == current), None)
        context["planning_context"] = {"chapter_plan": chapter_plan or {}, "active_threads": [item for item in planning.get("plot_threads", []) if item.get("status") == "active"], "open_foreshadowing": [item for item in planning.get("foreshadowing", []) if item.get("status") not in {"resolved", "abandoned"}]}
    except Exception:
        context["planning_context"] = {}
    json_path, markdown_path = save_current_context(context)
    return context, json_path, markdown_path

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
    context = build_working_context(state, memory_index, query, story_spec, characters, world_bible)
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
                save_json(vp["json_path"], refined)
                save_markdown(vp["markdown_path"], render_edited_markdown(refined))
                versions = load_versions_index(chapter_id)
                versions.setdefault("edited", [])
                versions["edited"].append({
                    "source_type": "edited",
                    "version": edit_version,
                    "version_label": f"edited_v{edit_version:03d}",
                    "json_path": vp["json_path"],
                    "markdown_path": vp["markdown_path"],
                    "actual_word_count": refined.get("actual_word_count", 0),
                    "mode": "api_model",
                    "quality_score": None,
                })
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
    save_json(str(_paths()["state"]), state)
    warnings = list(result.get("warnings", [])) + source_warnings
    context_json_path = ""
    context_markdown_path = ""
    try:
        context, context_json_path, context_markdown_path = _refresh_current_context_after_commit(paths, state)
        state["context"] = {
            "created": True,
            "json_path": context_json_path,
            "markdown_path": context_markdown_path,
            "recent_raw_chapters": 3,
            "older_chapters_strategy": "summary_only",
        }
        save_json(str(paths["state"]), state)
        warnings.extend(context.get("warnings", []))
    except Exception as exc:
        warnings.append(f"Writing context refresh failed; run build-context to retry: {str(exc)[:160]}")
    reflection_job = None
    try:
        from system.job_manager import get_job_manager
        reflection_job = get_job_manager().create_job("chapter_reflection", {"chapter_id": chapter_id, "created_by": "system"}, context=get_project_context())
    except Exception as exc:
        warnings.append(f"创作复盘待重试：{str(exc)[:160]}")
    try:
        from planning_engine.rolling_integration import mark_anchor_changed
        rolling_notice = mark_anchor_changed(get_project_context(), "canon_commit")
        if rolling_notice.get("warning") and rolling_notice.get("changed"):
            warnings.append(str(rolling_notice["warning"]))
    except Exception as exc:
        warnings.append(f"Rolling window status check can be retried manually: {str(exc)[:160]}")
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
            "context_json_path": context_json_path,
            "context_markdown_path": context_markdown_path,
            "creative_reflection_job_id": reflection_job.get("job_id") if reflection_job else None,
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
    result = sync_to_obsidian(get_project_context().data_dir, vault_dir, project_name)
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
        save_json(str(_paths()["state"]), state)
    return _success("sync-obsidian", "Obsidian 同步完成。", outputs=result, warnings=result.get("warnings", []))


def index_vault_command() -> dict[str, Any]:
    from system.vector_memory import build_or_update_index

    result = build_or_update_index(get_project_context().data_dir)
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
        chapter_path = Path("data") / "chapters" / f"chapter_{int(committed_chapter):03d}.md"
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


def _raw_selected_version(chapter_id: int) -> dict[str, Any]:
    path = Path("data") / "versions" / f"chapter_{chapter_id:03d}_versions.json"
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
