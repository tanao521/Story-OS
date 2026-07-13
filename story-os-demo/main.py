from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

import commands as command_api
import config
from config import DATA_DIR
from core.blueprint_generator import generate_blueprint, render_blueprint_markdown
from core.chapter_committer import (
    commit_chapter,
    render_committed_chapter_markdown,
)
from core.character_builder import generate_characters, render_characters_markdown
from core.draft_editor import edit_draft, render_edited_markdown
from core.draft_writer import render_draft_markdown, write_chapter_draft
from core.next_chapter_planner import (
    plan_next_chapter,
    render_next_chapter_plan_markdown,
)
from core.project import ensure_project_structure, resolve_current_project_root
from core.setup_wizard import (
    build_initial_state,
    render_project_markdown,
    run_setup_wizard,
)
from core.world_builder import generate_world_bible, render_world_bible_markdown
from llm.config_check import check_llm_config
from llm.openai_compatible_client import OpenAICompatibleClient
from llm.planning_service import (
    create_deepseek_client,
    generate_blueprint_with_deepseek,
    generate_story_spec_with_deepseek,
    plan_next_chapter_with_deepseek,
    should_use_deepseek_for_planning,
)
from system.context_builder import build_working_context, save_current_context
from system.file_store import ensure_data_dir, load_json, save_json, save_markdown
from system.pipeline_runner import run_single_chapter_pipeline
from system.review_gate import (
    find_current_review_target,
    prepare_review_record,
    save_review_markdown,
    save_review_record,
    update_review_status,
)
from system.obsidian_sync import (
    load_local_config,
    resolve_obsidian_config,
    save_local_config,
    sync_to_obsidian,
)
from system.status_dashboard import build_status_dashboard, render_status_text, save_status_report
from system.story_qa import (
    answer_from_memory,
    answer_from_state,
    answer_from_story,
    format_qa_text,
    save_qa_log,
)
from system.todo_manager import (
    create_todo,
    create_todos_from_quality_report,
    delete_todo,
    edit_todo,
    format_todo_for_cli,
    list_todos,
    load_todos,
    render_todos_markdown,
    save_todos,
    update_todo_status,
)
from system.validators import validate_story_spec


def main() -> None:
    from core.project import resolve_current_project_root
    os.chdir(resolve_current_project_root())
    command = sys.argv[1] if len(sys.argv) > 1 else "setup"

    if command == "status":
        run_status_command()
        return
    if command == "memory-health":
        run_memory_health_command(sys.argv[2:])
        return
    if command == "self-check":
        run_self_check_command(sys.argv[2:])
        return
    if command == "web":
        run_web_server()
        return
    if command == "todo":
        run_todo_command(sys.argv[2:])
        return
    if command == "shell":
        from system.interactive_shell import run_interactive_shell

        run_interactive_shell()
        return
    if command == "ask-state":
        run_ask_command("state", sys.argv[2:])
        return
    if command == "ask-memory":
        run_ask_command("memory", sys.argv[2:])
        return
    if command == "ask-story":
        run_ask_command("story", sys.argv[2:])
        return
    if command == "setup":
        run_setup_command()
        return
    if command == "blueprint":
        run_blueprint_command()
        return
    if command == "build-assets":
        run_build_assets_command()
        return
    if command == "plan-next":
        run_plan_next_command()
        return
    if command == "write-draft":
        run_write_draft_command()
        return
    if command == "regenerate-draft":
        run_regenerate_draft_command()
        return
    if command == "edit-draft":
        run_edit_draft_command()
        return
    if command == "reedit-draft":
        run_reedit_draft_command()
        return
    if command == "compare-drafts":
        run_compare_drafts_command()
        return
    if command == "quality-check":
        run_quality_check_command()
        return
    if command == "review-draft":
        run_review_draft_command()
        return
    if command == "commit-chapter":
        run_commit_chapter_command()
        return
    if command == "build-context":
        run_build_context_command()
        return
    if command == "sync-obsidian":
        run_sync_obsidian_command()
        return
    if command == "index-vault":
        run_index_vault_command()
        return
    if command == "run-chapter":
        run_chapter_pipeline_command()
        return
    if command == "check-llm":
        run_check_llm_command("--ping" in sys.argv[2:])
        return
    if command == "configure-llm":
        run_configure_llm_command(sys.argv[2:])
        return
    if command == "outline":
        print("当前系统采用逐章写作模式，请使用 python main.py blueprint 生成全书蓝图。")
        return

    print("未知命令。可用命令：")
    for item in [
        "status",
        "memory-health",
        "self-check",
        "web",
        "todo",
        "shell",
        "ask-story",
        "ask-memory",
        "ask-state",
        "setup",
        "blueprint",
        "build-assets",
        "plan-next",
        "write-draft",
        "regenerate-draft",
        "edit-draft",
        "compare-drafts",
        "quality-check",
        "reedit-draft",
        "review-draft",
        "commit-chapter",
        "build-context",
        "sync-obsidian",
        "index-vault",
        "run-chapter",
        "check-llm",
        "configure-llm",
    ]:
        print(f"- python main.py {item}")
    raise SystemExit(2)



def run_self_check_command(args: list[str]) -> None:
    allowed = {"--json"}
    unknown = [item for item in args if item not in allowed]
    if unknown:
        print("Unknown self-check option: " + " ".join(unknown))
        print("Usage: python main.py self-check [--json]")
        return
    command_api.self_check_command(json_output="--json" in args)


def run_memory_health_command(args: list[str]) -> None:
    if "--fix" in args:
        print("--fix will be implemented in v2.4-B.")
        return
    command_api.memory_health_command(json_output="--json" in args, full="--full" in args)




def run_web_server() -> None:
    import webbrowser

    import uvicorn

    defaults = {"host": "127.0.0.1", "port": 7860, "open_browser": True}
    local_config = load_local_config()
    web_config = local_config.get("web", {})
    if not isinstance(web_config, dict):
        web_config = {}
    changed = False
    for key, value in defaults.items():
        if key not in web_config:
            web_config[key] = value
            changed = True
    if local_config.get("web") != web_config:
        local_config["web"] = web_config
        changed = True
    if changed:
        save_local_config(local_config)

    host = str(web_config.get("host") or defaults["host"])
    port = int(web_config.get("port") or defaults["port"])
    url = f"http://{host}:{port}"
    print("Story OS Web 控制台已启动：")
    print(url)
    print()
    print("按 Ctrl+C 停止。")
    if bool(web_config.get("open_browser", True)):
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run("web.app:app", host=host, port=port, reload=False)

def run_ask_command(mode: str, args: list[str]) -> None:
    json_mode = "--json" in args
    no_log = "--no-log" in args
    use_vector = "--no-vector" not in args
    use_llm = "--llm" in args or (mode == "story" and bool(getattr(config, "USE_DEEPSEEK_FOR_QA", False)))
    question = _ask_question_arg(args)
    if not question:
        message = "请提供问题，例如：python main.py ask-state \"现在第几章？\""
        if json_mode:
            import json

            print(json.dumps({
                "qa_version": "1.9",
                "question": "",
                "answer": message,
                "mode": mode,
                "confidence": "unknown",
                "sources": [],
                "related": {"chapters": [], "characters": [], "foreshadows": [], "todos": [], "quality_reports": []},
                "warnings": [message],
            }, ensure_ascii=False, indent=2))
        else:
            print(message)
        return
    try:
        if mode == "state":
            result = answer_from_state(question)
        elif mode == "memory":
            result = answer_from_memory(question, use_vector=use_vector)
        else:
            result = answer_from_story(question, use_llm=use_llm, use_vector=use_vector)
    except Exception as exc:
        result = {
            "qa_version": "1.9",
            "question": question,
            "answer": f"问答失败：{exc}",
            "mode": mode,
            "confidence": "unknown",
            "sources": [],
            "related": {"chapters": [], "characters": [], "foreshadows": [], "todos": [], "quality_reports": []},
            "warnings": [str(exc)],
        }
    if not no_log:
        json_path, markdown_path = save_qa_log(result)
        result.setdefault("logs", {})["json_path"] = json_path
        result.setdefault("logs", {})["markdown_path"] = markdown_path
    if json_mode:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(format_qa_text(result))


def _ask_question_arg(args: list[str]) -> str:
    ignored = {"--json", "--no-log", "--no-vector", "--llm"}
    for item in args:
        if item not in ignored:
            return item
    return ""

def run_todo_command(args: list[str]) -> None:
    action = args[0] if args else "list"
    rest = args[1:] if args else []
    try:
        if action == "add":
            _run_todo_add(rest)
            return
        if action == "list":
            _run_todo_list(rest)
            return
        if action == "done":
            item = update_todo_status(_required_todo_id(rest), "done")
            print(f"任务 #{item['id']} 已完成。")
            return
        if action == "reopen":
            item = update_todo_status(_required_todo_id(rest), "open")
            print(f"任务 #{item['id']} 已重新打开。")
            return
        if action == "delete":
            item = delete_todo(_required_todo_id(rest))
            print(f"任务 #{item['id']} 已取消。")
            return
        if action == "edit":
            _run_todo_edit(rest)
            return
        if action == "from-quality":
            _run_todo_from_quality(rest)
            return
    except Exception as exc:
        print(f"todo 命令失败：{exc}")
        return
    print("未知 todo 命令。可用：add / list / done / reopen / delete / edit / from-quality")


def _run_todo_add(args: list[str]) -> None:
    title = _first_positional(args)
    if not title:
        print('请提供任务内容，例如：python main.py todo add "重写第3章结尾"')
        return
    item = create_todo(
        title,
        todo_type=_todo_value(args, "--type") or "other",
        priority=_todo_value(args, "--priority") or "medium",
        chapter_id=_todo_int_value(args, "--chapter"),
    )
    print("已新增任务：")
    print()
    print(format_todo_for_cli(item))


def _run_todo_list(args: list[str]) -> None:
    status = _todo_value(args, "--status")
    todo_type = _todo_value(args, "--type")
    chapter_id = _todo_int_value(args, "--chapter")
    items = list_todos(status=status, todo_type=todo_type, chapter_id=chapter_id)
    print("Story OS 待办事项")
    print()
    if status or todo_type or chapter_id is not None:
        for item in items:
            print(f"- {format_todo_for_cli(item)}")
        if not items:
            print("- 暂无")
        return
    grouped = {
        "open": "Open",
        "in_progress": "In Progress",
        "done": "Done",
        "cancelled": "Cancelled",
    }
    for key, title in grouped.items():
        print(f"{title}:")
        group_items = [item for item in items if item.get("status") == key]
        if not group_items:
            print("- 暂无")
        for item in group_items:
            print(f"- {format_todo_for_cli(item)}")
        print()


def _run_todo_edit(args: list[str]) -> None:
    todo_id = _required_todo_id(args)
    title = _first_positional(args[1:])
    item = edit_todo(
        todo_id,
        title=title,
        priority=_todo_value(args, "--priority"),
        todo_type=_todo_value(args, "--type"),
        chapter_id=_todo_int_value(args, "--chapter"),
    )
    print(f"任务 #{item['id']} 已更新。")


def _run_todo_from_quality(args: list[str]) -> None:
    report_path = _todo_value(args, "--report")
    if not report_path:
        status = build_status_dashboard(full=False)
        report_path = str(status.get("quality", {}).get("latest_report_path", ""))
    if not report_path or not Path(report_path).exists():
        print("当前选中版本没有质量报告。请先运行：")
        print("python main.py quality-check")
        return
    created = create_todos_from_quality_report(report_path)
    print(f"已从质量报告生成 {len(created)} 个待办任务。")


def _required_todo_id(args: list[str]) -> int:
    if not args:
        raise ValueError("缺少任务 id")
    return int(args[0])


def _first_positional(args: list[str]) -> str:
    for item in args:
        if not item.startswith("--"):
            return item
    return ""


def _todo_value(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    index = args.index(flag)
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _todo_int_value(args: list[str], flag: str) -> int | None:
    value = _todo_value(args, flag)
    if value is None:
        return None
    return int(value)

def run_status_command() -> None:
    full = "--full" in sys.argv[2:] or "--json" in sys.argv[2:]
    json_mode = "--json" in sys.argv[2:]
    status = build_status_dashboard(full=full)
    save_status_report(status)
    if json_mode:
        import json

        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    print(render_status_text(status, full=full))


def run_setup_command() -> None:
    story_spec = run_setup_wizard()
    client, config_warnings = _planning_client_or_none()
    if client is not None:
        story_spec, planning_warnings = generate_story_spec_with_deepseek(
            story_spec,
            story_spec,
            client,
        )
        _print_warnings(config_warnings + planning_warnings)
    else:
        _print_warnings(config_warnings)
    errors = validate_story_spec(story_spec)
    if errors:
        print("项目设定校验失败：")
        for error in errors:
            print(f"- {error}")
        return

    state = build_initial_state(story_spec)
    project_root = resolve_current_project_root()
    ensure_data_dir()
    save_json("data/story_spec.json", story_spec)
    save_json("data/state.json", state)
    save_markdown("data/project.md", render_project_markdown(story_spec))
    structure = ensure_project_structure(project_root, form_data=story_spec)
    print(f"[project] project_root = {project_root}")
    print(f"[project] blueprint_path = {structure['blueprint_path']}")
    print("小说项目已初始化完成。")
    planning_result = command_api.initialize_planning_command(
        use_deepseek=bool(story_spec.get("use_deepseek", False))
    )
    if planning_result.get("status") == "failed":
        print("项目已创建，但规划层初始化失败：")
        print(planning_result.get("message", "unknown planning error"))
    else:
        print("故事蓝图、角色档案、世界观设定和首章计划已自动生成。")

def run_blueprint_command() -> None:
    paths = _required_project_paths()
    if not paths["story_spec"].exists():
        print("未找到 data/story_spec.json，请先运行 python main.py setup。")
        return

    story_spec = load_json(str(paths["story_spec"]))
    errors = validate_story_spec(story_spec)
    if errors:
        print("项目设定校验失败，无法生成蓝图：")
        for error in errors:
            print(f"- {error}")
        return

    blueprint = generate_blueprint(story_spec)
    client, config_warnings = _planning_client_or_none()
    if client is not None:
        blueprint, planning_warnings = generate_blueprint_with_deepseek(
            story_spec,
            blueprint,
            client,
        )
        _print_warnings(config_warnings + planning_warnings)
    else:
        _print_warnings(config_warnings)
    state = _load_or_create_state(story_spec)
    _apply_blueprint_state_update(state)
    save_json("data/story_blueprint.json", blueprint)
    save_markdown("data/story_blueprint.md", render_blueprint_markdown(blueprint))
    save_json("data/state.json", state)
    print("全书高层蓝图已生成。")


def run_build_assets_command() -> None:
    paths = _required_project_paths()
    if not paths["story_spec"].exists():
        print("请先运行 python main.py setup 创建小说项目。")
        return
    if not paths["blueprint"].exists():
        print("请先运行 python main.py blueprint 创建故事蓝图。")
        return

    story_spec = load_json(str(paths["story_spec"]))
    blueprint = load_json(str(paths["blueprint"]))
    state = _load_or_create_state(story_spec)
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    _apply_assets_state_update(state, characters, world_bible)
    save_json("data/characters.json", characters)
    save_markdown("data/characters.md", render_characters_markdown(characters))
    save_json("data/world_bible.json", world_bible)
    save_markdown("data/world_bible.md", render_world_bible_markdown(world_bible))
    save_json("data/state.json", state)
    print("角色卡与世界观设定已生成。")


def run_plan_next_command() -> None:
    project_root = resolve_current_project_root()
    structure = ensure_project_structure(project_root)
    paths = _required_project_paths(project_root)
    missing_message = _missing_plan_next_input_message(paths)
    if missing_message:
        print(missing_message)
        return

    print(f"[plan-next] project_root = {project_root}")
    print(f"[plan-next] blueprint_path = {structure['blueprint_path']}")
    story_spec = load_json(str(paths["story_spec"]))
    blueprint = load_json(str(paths["blueprint"]))
    characters = load_json(str(paths["characters"]))
    world_bible = load_json(str(paths["world_bible"]))
    state = load_json(str(paths["state"])) if paths["state"].exists() else build_initial_state(story_spec)
    working_context = _load_optional_context(paths)
    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state, working_context)
    client, config_warnings = _planning_client_or_none()
    if client is not None:
        plan, planning_warnings = plan_next_chapter_with_deepseek(
            story_spec,
            blueprint,
            characters,
            world_bible,
            state,
            working_context,
            plan,
            client,
        )
        _print_warnings(config_warnings + planning_warnings)
    else:
        _print_warnings(config_warnings)
    _apply_next_chapter_plan_state_update(state, plan)
    save_json(str(paths["next_chapter_plan"]), plan)
    save_markdown(str(project_root / "data" / "next_chapter_plan.md"), render_next_chapter_plan_markdown(plan))
    save_json(str(paths["state"]), state)
    print("下一章计划已生成。")

def run_write_draft_command() -> None:
    _print_command_result(command_api.write_draft_command())


def run_edit_draft_command() -> None:
    draft_version = _optional_int_arg("--draft-version")
    _print_command_result(command_api.edit_draft_command(draft_version=draft_version))


def run_commit_chapter_command() -> None:
    _print_command_result(command_api.commit_chapter_command())


def run_build_context_command() -> None:
    _print_command_result(command_api.build_context_command())


def run_sync_obsidian_command() -> None:
    _print_command_result(command_api.sync_obsidian_command())


def run_review_draft_command() -> None:
    try:
        prepared = prepare_review_record("data")
    except Exception as exc:
        print(f"无法创建审核任务：{exc}")
        return

    target = prepared["target"]
    record = prepared["record"]
    save_review_record(record, "data")
    save_review_markdown(record, target, "data")
    while True:
        print("当前章审核：")
        print(f"- 章节：第{target.get('chapter_id', '')}章 {target.get('chapter_title', '')}")
        print(f"- 来源：{target.get('source_type', '')}")
        print(f"- 版本：{target.get('version_label', '') or target.get('version', '')}")
        print(f"- 文件：{target.get('json_path', '')}")
        print(f"- 字数：{len(str(target.get('text', '')))}")
        _print_review_quality_summary(target)
        print()
        print(str(target.get("text", ""))[:800])
        print()
        answer = input("请选择操作：approve / reject / later / show / versions / select / quality\n> ").strip().lower()
        if answer == "show":
            print(str(target.get("text", ""))[:3000])
            print()
            continue
        if answer == "versions":
            _print_versions(command_api.compare_drafts_command())
            print()
            continue
        if answer == "quality":
            _print_quality_result(command_api.quality_check_command())
            prepared = prepare_review_record("data")
            target = prepared["target"]
            record = prepared["record"]
            save_review_markdown(record, target, "data")
            print()
            continue
        if answer == "todo":
            todo_title = input("请输入待办内容：\n> ").strip()
            if not todo_title:
                print("待办内容不能为空。")
                continue
            item = create_todo(
                todo_title,
                todo_type="revision",
                priority="medium",
                chapter_id=int(target["chapter_id"]),
                related={"source": "review"},
            )
            print(f"已添加审核待办 #{item['id']}。")
            print()
            continue
        if answer == "select":
            spec = input("请输入版本，例如 edited:1 或 draft:2\n> ").strip()
            select_result = command_api.compare_drafts_command(select_spec=spec)
            _print_versions(select_result)
            if select_result.get("status") == "success":
                prepared = prepare_review_record("data")
                target = prepared["target"]
                record = prepared["record"]
                save_review_markdown(record, target, "data")
            print()
            continue
        if answer == "later":
            record = update_review_status(int(target["chapter_id"]), "pending", decision="later")
            state = _load_or_create_state({})
            state["current_stage"] = "waiting_for_review"
            state["review"] = {
                "chapter_id": target["chapter_id"],
                "status": "pending",
                "path": prepared["json_path"],
            }
            save_json("data/state.json", state)
            save_review_markdown(record, target, "data")
            print("已保存为待审核。章节未提交。")
            return
        if answer == "reject":
            record = update_review_status(int(target["chapter_id"]), "rejected", decision="reject")
            state = _load_or_create_state({})
            state["current_stage"] = "draft_rejected"
            state["review"] = {
                "chapter_id": target["chapter_id"],
                "status": "rejected",
                "path": prepared["json_path"],
            }
            save_json("data/state.json", state)
            save_review_markdown(record, target, "data")
            print("已拒绝当前草稿。章节未提交，current_chapter 未变化。")
            print("可以运行 regenerate-draft / reedit-draft / quality-check 后再审核。")
            return
        if answer == "approve":
            quality_summary = command_api.quality_summary_for_target(target)
            score = float(quality_summary.get("overall_score", 1.0) or 1.0) if quality_summary else 1.0
            if score < 0.65:
                print(f"当前版本质量评分较低：{score:.2f}")
                confirm = input("仍然提交吗？yes/no\\n> ").strip().lower()
                if confirm != "yes":
                    print("已取消提交。章节仍处于待审核状态。")
                    continue
            before = int(_load_or_create_state({}).get("current_chapter", 0) or 0)
            record = update_review_status(int(target["chapter_id"]), "approved", decision="approve")
            save_review_markdown(record, target, "data")
            commit_result = command_api.commit_chapter_command()
            if commit_result.get("status") == "failed":
                print(f"审核已批准，但提交失败：{commit_result.get('message', '')}")
                return
            sync_result = command_api.sync_obsidian_command()
            if sync_result.get("status") == "failed":
                print(f"警告：sync-obsidian 失败：{sync_result.get('message', '')}")
            index_result = command_api.index_vault_command()
            if index_result.get("status") == "failed":
                print(f"警告：index-vault 失败：{index_result.get('message', '')}")
            after = int(_load_or_create_state({}).get("current_chapter", before) or before)
            print("审核通过，章节已提交。")
            print(f"current_chapter: {before} -> {after}")
            return
        print("请输入 approve / reject / later / show / versions / select / quality。")


def run_index_vault_command() -> None:
    _print_command_result(command_api.index_vault_command())


def run_chapter_pipeline_command() -> None:
    auto_commit = "--auto-commit" in sys.argv[2:]
    report = run_single_chapter_pipeline(auto_commit=auto_commit)
    report_path = report.get("report_paths", {}).get("markdown_path", "")
    final_state = report.get("final_state", {})
    if report.get("status") == "waiting_for_review":
        print("当前章已生成并编辑完成，等待人工审核。")
        print()
        print("请运行：")
        print("python main.py review-draft")
        print()
        print("审核通过后才会提交为正式章节。")
        print(f"报告：{report_path}")
        if report.get("warnings"):
            print()
            print("Warnings:")
            for warning in report.get("warnings", []):
                print(f"- {warning}")
        return

    if report.get("status") in {"success", "success_with_warnings"}:
        print("单章流水线完成。")
        print()
        print(f"章节：第{report.get('chapter_id', '')}章")
        print(f"状态：{report.get('status', '')}")
        print(
            f"current_chapter: {final_state.get('current_chapter_before', '')} -> "
            f"{final_state.get('current_chapter_after', '')}"
        )
        print(f"报告：{report_path}")
        if report.get("warnings"):
            print()
            print("完成，但有 warning：")
            for warning in report.get("warnings", []):
                print(f"- {warning}")
        return

    failed_step = next(
        (step for step in report.get("steps", []) if step.get("status") == "failed"),
        {},
    )
    print("单章流水线失败。")
    print()
    print(f"失败步骤：{failed_step.get('name', '')}")
    print(f"错误：{failed_step.get('message', '')}")
    print(f"报告：{report_path}")




def run_quality_check_command() -> None:
    all_versions = "--all" in sys.argv[2:]
    draft_version = _optional_int_arg("--draft-version")
    edited_version = _optional_int_arg("--edited-version")
    manual_version = _optional_int_arg("--manual-version")
    _print_quality_result(
        command_api.quality_check_command(
            all_versions=all_versions,
            draft_version=draft_version,
            edited_version=edited_version,
            manual_version=manual_version,
        )
    )


def _print_quality_result(result: dict[str, Any]) -> None:
    if result.get("status") == "failed":
        print(result.get("message", "质量评估失败。"))
        return
    print(result.get("message", "质量评估完成。"))
    reports = result.get("outputs", {}).get("reports", [])
    for report in reports:
        print()
        print(f"章节：第{report.get('chapter_id', '')}章")
        print(f"版本：{report.get('version_label', '')}")
        print(f"总分：{float(report.get('overall_score', 0) or 0):.2f}")
        flags = report.get("flags", [])
        if flags:
            print("主要问题：")
            for item in flags[:3]:
                print(f"- {item.get('message', '')}")
        print("报告：")
        print(report.get("markdown_path", ""))


def _print_review_quality_summary(target: dict[str, Any]) -> None:
    summary = command_api.quality_summary_for_target(target)
    print()
    if not summary:
        print("质量评估：当前版本尚未生成质量评估。")
        print("建议运行：python main.py quality-check")
        return
    print("质量评估：")
    print(f"- 总分：{float(summary.get('overall_score', 0) or 0):.2f}")
    print(f"- AI味风险：{summary.get('ai_risk', 'low')}")
    print(f"- 连续性风险：{summary.get('continuity_risk', 'low')}")
    print(f"- 结尾钩子：{summary.get('hook_strength', '')}")


def run_regenerate_draft_command() -> None:
    _print_command_result(command_api.regenerate_draft_command())


def run_reedit_draft_command() -> None:
    draft_version = _optional_int_arg("--draft-version")
    _print_command_result(command_api.reedit_draft_command(draft_version=draft_version))


def run_compare_drafts_command() -> None:
    select_spec = _optional_value_arg("--select")
    _print_versions(command_api.compare_drafts_command(select_spec=select_spec))


def _optional_value_arg(flag: str) -> str | None:
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def _optional_int_arg(flag: str) -> int | None:
    value = _optional_value_arg(flag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        print(f"{flag} 需要整数，已忽略。")
        return None


def _print_command_result(result: dict[str, Any]) -> None:
    if result.get("status") == "failed":
        print(result.get("message", "命令失败。"))
        return
    print(result.get("message", "命令完成。"))
    outputs = result.get("outputs", {})
    for key in [
        "chapter_id",
        "version_label",
        "source_draft_version",
        "json_path",
        "markdown_path",
        "versioned_json_path",
        "versioned_markdown_path",
        "chapter_path",
        "summary_path",
        "source_used",
        "source_version",
        "source_path",
        "path",
    ]:
        if key in outputs and outputs[key] not in {"", None}:
            print(f"- {key}: {outputs[key]}")
    for warning in result.get("warnings", []):
        print(f"警告：{warning}")


def _print_versions(result: dict[str, Any]) -> None:
    if result.get("status") == "failed":
        print(result.get("message", "版本列表生成失败。"))
        return
    outputs = result.get("outputs", {})
    print(result.get("message", "版本列表："))
    selected = outputs.get("selected", {})
    if isinstance(selected, dict) and selected:
        print(f"Selected: {selected.get('source_type', '')}:{selected.get('version', '')} {selected.get('json_path', '')}")
    for title, key in [("Drafts", "drafts"), ("Edited", "edited"), ("Manual", "manual")]:
        print()
        print(title + ":")
        items = outputs.get(key, [])
        if not items:
            print("- 暂无")
            continue
        for item in items:
            preview = str(item.get("preview", "")).replace("\\n", " ")[:300]
            print(
                f"- {item.get('source_type', '')}:{item.get('version', '')} "
                f"{item.get('version_label', '')} chars={item.get('actual_word_count', 0)} "
                f"mode={item.get('mode', '')} fallback={item.get('fallback_used', False)} "
                f"score={item.get('quality_score', '未评估') if item.get('quality_score') is not None else '未评估'} "
                f"AI风险={item.get('quality_ai_risk', '')}"
            )
            print(f"  path={item.get('json_path', '')}")
            print(f"  preview={preview}")
    for warning in result.get("warnings", []):
        print(f"警告：{warning}")


def run_configure_llm_command(args: list[str]) -> None:
    local_config = load_local_config()
    if "--disable" in args:
        enabled = False
    elif "--enable" in args:
        enabled = True
    else:
        answer = input("是否启用 DeepSeek 规划层？API Key 只从 .env 读取。（yes/no，默认 yes）\n> ").strip().lower()
        enabled = answer not in {"no", "n"}

    local_config["use_deepseek_for_planning"] = enabled
    save_local_config(local_config)
    print(f"DeepSeek 规划层开关已更新：{'启用' if enabled else '关闭'}")
    print("API Key 仍只允许保存在 .env，不会写入 .story_os/config.json。")


def _planning_client_or_none() -> tuple[Any | None, list[str]]:
    local_config = load_local_config()
    if not local_config.get("use_deepseek_for_planning", False):
        return None, []
    if not config.DEEPSEEK_API_KEY:
        return None, ["已启用 DeepSeek 规划层，但未检测到 DEEPSEEK_API_KEY，已使用本地 mock。"]
    if not should_use_deepseek_for_planning(local_config):
        return None, ["DeepSeek 规划层配置不完整，已使用本地 mock。"]
    return create_deepseek_client(), []


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"提示：{warning}")


def run_check_llm_command(ping: bool = False) -> None:
    result = check_llm_config()
    write_model = result["write_model"]
    deepseek = result["deepseek"]

    from core.llm_api_model import generate_with_api_model, load_api_model_settings

    print("LLM ???")
    print()
    print("?????? API ???")
    print(f"- API Key: {write_model['api_key_masked']}")
    print(f"- Model: {write_model['model']}")
    print(f"- Base URL: {write_model['base_url']}")
    print(f"- ??: {'??' if write_model['api_key_present'] and write_model['model'] and write_model['base_url'] else '?????'}")
    print()
    print("DeepSeek?")
    print(f"- API Key: {deepseek['api_key_masked']}")
    print(f"- Model: {deepseek['model']}")
    print(f"- Base URL: {deepseek['base_url']}")
    print(f"- ??: {'??' if deepseek['api_key_present'] and deepseek['model'] and deepseek['base_url'] else '?????'}")

    if result["warnings"]:
        print()
        print("???")
        for warning in result["warnings"]:
            print(f"- {warning}")

    if not ping:
        print()
        print("????? `python main.py check-llm --ping` ??????????")
        return

    print()
    print("Ping?")
    try:
        settings = load_api_model_settings()
        reply = generate_with_api_model([
            {"role": "system", "content": "????? Story OS ????? API ??????????????????"},
            {"role": "user", "content": "??? OK?"},
        ])
        print(f"- API ???: ??????{reply.strip()[:80]}")
    except Exception as exc:
        print(f"- API ???: ???{exc}")

    if deepseek["api_key_present"] and deepseek["model"] and deepseek["base_url"]:
        _ping_model("DeepSeek", config.DEEPSEEK_API_KEY, config.DEEPSEEK_BASE_URL, config.DEEPSEEK_MODEL)

def _ping_model(name: str, api_key: str, base_url: str, model: str) -> None:
    if not base_url or not model:
        print(f"- {name}: 跳过，base_url 或 model 未配置。")
        return
    try:
        client = OpenAICompatibleClient(api_key=api_key, base_url=base_url, model=model)
        reply = client.chat_text("只回复 OK")
    except Exception as exc:
        print(f"- {name}: 失败：{exc}")
        return
    print(f"- {name}: 成功，回复：{reply.strip()[:80]}")


def _required_project_paths(project_root: Path | None = None) -> dict[str, Path]:
    root = project_root or Path.cwd()
    return {
        "story_spec": root / "data" / "story_spec.json",
        "state": root / "data" / "state.json",
        "blueprint": root / "data" / "story_blueprint.json",
        "characters": root / "data" / "characters.json",
        "world_bible": root / "data" / "world_bible.json",
        "next_chapter_plan": root / "data" / "next_chapter_plan.json",
        "memory_index": root / "data" / "memory" / "memory_index.json",
        "current_context": root / "data" / "context" / "current_context.json",
        "edited_dir": root / "data" / "edited",
    }


def _missing_plan_next_input_message(paths: dict[str, Path]) -> str:
    if not paths["story_spec"].exists():
        return "请先运行 python main.py setup 创建小说项目。"
    if not paths["blueprint"].exists():
        return "story_blueprint.json 自动修复失败，请检查 logs/generation.log。"
    if not paths["characters"].exists() or not paths["world_bible"].exists():
        return "请先运行 python main.py build-assets 创建角色卡和世界观设定。"
    return ""


def _missing_write_draft_input_message(paths: dict[str, Path]) -> str:
    missing = _missing_plan_next_input_message(paths)
    if missing:
        return missing
    if not paths["next_chapter_plan"].exists():
        return "请先运行 python main.py plan-next 生成下一章计划。"
    return ""


def _load_optional_context(paths: dict[str, Path]) -> dict[str, Any] | None:
    if paths["current_context"].exists():
        return load_json(str(paths["current_context"]))
    return None


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
        parts.extend(str(item.get("content", "")) for item in foreshadows if isinstance(item, dict) and item.get("status") in {"open", "planned"})
    if paths["next_chapter_plan"].exists():
        plan = load_json(str(paths["next_chapter_plan"]))
        parts.append(str(plan.get("chapter_goal", "")))
        parts.append(str(plan.get("conflict_design", {}).get("main_conflict", "")))
        parts.append(str(plan.get("pacing_design", {}).get("ending_hook", "")))
    return " ".join(part for part in parts if part)


def _load_or_create_state(story_spec: dict[str, Any]) -> dict[str, Any]:
    state_path = Path("data/state.json")
    if state_path.exists():
        return load_json(str(state_path))
    return build_initial_state(story_spec)


def _apply_blueprint_state_update(state: dict[str, Any]) -> None:
    state["current_stage"] = "blueprint_created"
    state["blueprint"] = {
        "created": True,
        "path": "data/story_blueprint.json",
        "mode": "chapter_by_chapter",
    }
    memory_policy = state.setdefault("memory_policy", {})
    memory_policy["working_context_chapters"] = 3
    memory_policy["older_chapters_strategy"] = "summarize_and_retrieve"
    memory_policy["use_vector_memory_later"] = True


def _apply_assets_state_update(
    state: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
) -> None:
    state["current_stage"] = "assets_created"
    state["assets"] = {
        "characters_created": True,
        "world_bible_created": True,
        "characters_path": "data/characters.json",
        "world_bible_path": "data/world_bible.json",
    }
    state["world"] = {
        "style": world_bible.get("world_style", ""),
        "rules": [
            rule.get("rule", "")
            for rule in world_bible.get("core_rules", [])
            if rule.get("rule", "")
        ],
        "locations": [
            location.get("name", "")
            for location in world_bible.get("locations", [])
            if location.get("name", "")
        ],
    }
    state_characters = state.setdefault("characters", {})
    for character in characters.get("main_characters", []):
        current_state = character.get("current_state", {})
        state_characters[character.get("name", character.get("id", ""))] = {
            "physical": current_state.get("physical", ""),
            "mental": current_state.get("mental", ""),
            "goal": character.get("external_goal", ""),
        }


def _apply_next_chapter_plan_state_update(
    state: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    state["current_stage"] = "next_chapter_planned"
    state["next_chapter_plan"] = {
        "created": True,
        "chapter_id": plan.get("chapter_id", 1),
        "path": "data/next_chapter_plan.json",
    }


def _apply_draft_state_update(
    state: dict[str, Any],
    draft: dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> None:
    state["current_stage"] = "chapter_draft_created"
    state["draft"] = {
        "created": True,
        "chapter_id": draft.get("chapter_id", 1),
        "status": "draft",
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
    }


def _apply_context_state_update(state: dict[str, Any], json_path: str, markdown_path: str) -> None:
    state["current_stage"] = "context_built"
    state["context"] = {
        "created": True,
        "json_path": json_path,
        "markdown_path": markdown_path,
        "recent_raw_chapters": 3,
        "older_chapters_strategy": "summary_only",
    }


def _apply_obsidian_state_update(state: dict[str, Any], result: dict[str, Any]) -> None:
    state["current_stage"] = "obsidian_synced"
    state["obsidian"] = {
        "synced": True,
        "vault_dir": result.get("obsidian_vault_dir", ""),
        "project_root": result.get("obsidian_project_root", ""),
        "index_path": result.get("index_path", ""),
        "sync_version": "0.8",
    }


def _draft_paths(chapter_id: int) -> tuple[Path, Path]:
    file_stem = f"chapter_{chapter_id:03d}_draft"
    return Path("data/drafts") / f"{file_stem}.json", Path("data/drafts") / f"{file_stem}.md"


def _edited_paths(chapter_id: int) -> tuple[Path, Path]:
    file_stem = f"chapter_{chapter_id:03d}_edited"
    return Path("data/edited") / f"{file_stem}.json", Path("data/edited") / f"{file_stem}.md"


if __name__ == "__main__":
    main()
