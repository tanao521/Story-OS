from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from config import CONFIG_DIR, LOCAL_CONFIG_PATH


OBSIDIAN_DIRS = [
    "00_Project",
    "01_World",
    "02_Characters",
    "03_Chapters",
    "04_Summaries",
    "05_Foreshadows",
    "06_Timeline",
    "07_Plans",
    "08_Drafts",
    "09_Edited",
    "10_Manual",
    "10_Versions",
    "11_Quality_Reports",
    "12_Status",
    "13_Todos",
    "14_QA_Logs",
    "15_Shell_Logs",
    "99_Index",
]

WINDOWS_INVALID_FILENAME_CHARS = r'<>:"/\\|?*'


def load_local_config() -> dict[str, Any]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))


def save_local_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_obsidian_config() -> dict[str, Any]:
    config = load_local_config()
    if not config.get("obsidian_vault_dir"):
        config["obsidian_vault_dir"] = input("请输入你的 Obsidian Vault 路径：\n> ").strip()
    if not config.get("obsidian_project_dir_name"):
        project_name = input("请输入要在 Obsidian 中创建的项目文件夹名，留空则使用 StoryOS：\n> ").strip()
        config["obsidian_project_dir_name"] = project_name or "StoryOS"
    save_local_config(config)
    return config


def ensure_obsidian_structure(
    obsidian_vault_dir: str | Path,
    project_dir_name: str,
) -> dict[str, Any]:
    project_root = Path(obsidian_vault_dir) / project_dir_name
    created_dirs: list[str] = []
    existing_dirs: list[str] = []
    for directory_name in [""] + OBSIDIAN_DIRS:
        directory = project_root / directory_name if directory_name else project_root
        if directory.exists():
            existing_dirs.append(directory.as_posix())
        else:
            directory.mkdir(parents=True, exist_ok=True)
            created_dirs.append(directory.as_posix())
    return {
        "project_root": project_root.as_posix(),
        "created_dirs": created_dirs,
        "existing_dirs": existing_dirs,
    }


def sync_to_obsidian(
    data_dir: str | Path,
    obsidian_vault_dir: str | Path,
    project_dir_name: str,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    structure = ensure_obsidian_structure(obsidian_vault_dir, project_dir_name)
    project_root = Path(structure["project_root"])
    synced_files: list[str] = []
    warnings: list[str] = []

    _sync_project_files(data_path, project_root, synced_files, warnings)
    _sync_world_files(data_path, project_root, synced_files, warnings)
    _sync_character_files(data_path, project_root, synced_files, warnings)
    _sync_chapters(data_path, project_root, synced_files, warnings)
    _sync_summaries(data_path, project_root, synced_files, warnings)
    _sync_state_tables(data_path, project_root, synced_files, warnings)
    _sync_plans_and_context(data_path, project_root, synced_files, warnings)
    _sync_drafts(data_path, project_root, synced_files, warnings)
    _sync_edited_versions(data_path, project_root, synced_files, warnings)
    _sync_manual_versions(data_path, project_root, synced_files, warnings)
    _sync_versions(data_path, project_root, synced_files, warnings)
    _sync_quality_reports(data_path, project_root, synced_files, warnings)
    _sync_status_report(data_path, project_root, synced_files, warnings)
    _sync_todos(data_path, project_root, synced_files, warnings)
    _sync_qa_logs(data_path, project_root, synced_files, warnings)
    _sync_shell_logs(data_path, project_root, synced_files, warnings)
    index_path = _write_index(project_root, synced_files)

    return {
        "sync_version": "0.8",
        "obsidian_vault_dir": Path(obsidian_vault_dir).as_posix(),
        "obsidian_project_root": project_root.as_posix(),
        "synced_files": synced_files,
        "warnings": warnings,
        "index_path": index_path,
    }


def _sync_project_files(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    _copy_markdown(data_path / "project.md", project_root / "00_Project" / "Project.md", synced_files, warnings)
    _json_to_markdown(data_path / "story_spec.json", project_root / "00_Project" / "Story_Spec.md", "Story Spec", synced_files, warnings)
    _json_to_markdown(data_path / "story_blueprint.json", project_root / "00_Project" / "Story_Blueprint.md", "Story Blueprint", synced_files, warnings)
    _json_to_markdown(data_path / "state.json", project_root / "00_Project" / "State.md", "State", synced_files, warnings)


def _sync_world_files(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    _copy_markdown(data_path / "world_bible.md", project_root / "01_World" / "World_Bible.md", synced_files, warnings)
    _json_to_markdown(data_path / "world_bible.json", project_root / "01_World" / "World_Bible_Data.md", "World Bible Data", synced_files, warnings)


def _sync_character_files(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    target_dir = project_root / "02_Characters"
    _copy_markdown(data_path / "characters.md", target_dir / "Characters.md", synced_files, warnings)
    characters_json = data_path / "characters.json"
    if not characters_json.exists():
        warnings.append("缺少可选文件：data/characters.json")
        return
    characters = _read_json(characters_json)
    all_characters = characters.get("main_characters", []) + characters.get("supporting_characters", [])
    for character in all_characters:
        if not isinstance(character, dict):
            continue
        filename = _safe_filename(f"{character.get('id', 'char')}_{character.get('name', '角色')}.md")
        target = target_dir / filename
        target.write_text(_render_character_markdown(character), encoding="utf-8")
        synced_files.append(target.as_posix())


def _sync_chapters(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    chapters_dir = data_path / "chapters"
    if not chapters_dir.exists():
        warnings.append("缺少可选目录：data/chapters")
        return
    for source in sorted(chapters_dir.glob("*.md")):
        _copy_markdown(source, project_root / "03_Chapters" / source.name, synced_files, warnings)


def _sync_summaries(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    summaries_dir = data_path / "summaries"
    if not summaries_dir.exists():
        warnings.append("缺少可选目录：data/summaries")
        return
    for source in sorted(summaries_dir.glob("*.json")):
        summary = _read_json(source)
        target = project_root / "04_Summaries" / f"{source.stem}.md"
        target.write_text(_render_summary_markdown(summary), encoding="utf-8")
        synced_files.append(target.as_posix())


def _sync_state_tables(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    state_path = data_path / "state.json"
    if not state_path.exists():
        warnings.append("缺少可选文件：data/state.json")
        return
    state = _read_json(state_path)
    foreshadows_path = project_root / "05_Foreshadows" / "Foreshadows.md"
    foreshadows_path.write_text(_render_foreshadows_markdown(state.get("foreshadows", [])), encoding="utf-8")
    synced_files.append(foreshadows_path.as_posix())
    timeline_path = project_root / "06_Timeline" / "Timeline.md"
    timeline_path.write_text(_render_timeline_markdown(state.get("timeline", [])), encoding="utf-8")
    synced_files.append(timeline_path.as_posix())


def _sync_plans_and_context(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    _copy_markdown(data_path / "next_chapter_plan.md", project_root / "07_Plans" / "Next_Chapter_Plan.md", synced_files, warnings)
    _copy_markdown(data_path / "context" / "current_context.md", project_root / "07_Plans" / "Current_Context.md", synced_files, warnings)


def _sync_drafts(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    drafts_dir = data_path / "drafts"
    if not drafts_dir.exists():
        warnings.append("缺少可选目录：data/drafts")
        return
    for source in sorted(drafts_dir.glob("*.md")):
        _copy_markdown(source, project_root / "08_Drafts" / source.name, synced_files, warnings)



def _sync_edited_versions(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    edited_dir = data_path / "edited"
    if not edited_dir.exists():
        warnings.append("缺少可选目录：data/edited")
        return
    for source in sorted(edited_dir.glob("*_v*.md")):
        _copy_markdown(source, project_root / "09_Edited" / source.name, synced_files, warnings)


def _sync_manual_versions(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    manual_dir = data_path / "manual"
    if not manual_dir.exists():
        warnings.append("缺少可选目录：data/manual")
        return
    for source in sorted(manual_dir.glob("*_v*.md")):
        _copy_markdown(source, project_root / "10_Manual" / source.name, synced_files, warnings)


def _sync_versions(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    versions_dir = data_path / "versions"
    if not versions_dir.exists():
        warnings.append("缺少可选目录：data/versions")
        return
    for source in sorted(versions_dir.glob("*.json")):
        data = _read_json(source)
        target = project_root / "10_Versions" / f"{source.stem}.md"
        target.write_text(_render_versions_markdown(data), encoding="utf-8")
        synced_files.append(target.as_posix())


def _render_versions_markdown(data: dict[str, Any]) -> str:
    selected = data.get("selected", {})
    rows = [
        f"# 第{data.get('chapter_id', '')}章版本索引",
        "",
        "## Drafts",
        "",
        "| Version | Label | Mode | Fallback | Path |",
        "|---|---|---|---|---|",
    ]
    for item in data.get("drafts", []):
        rows.append(
            f"| {item.get('version', '')} | {item.get('version_label', '')} | {item.get('mode', '')} | {item.get('fallback_used', '')} | {item.get('json_path', '')} |"
        )
    rows.extend(["", "## Edited", "", "| Version | Label | Source Draft | Mode | Fallback | Path |", "|---|---|---|---|---|---|"])
    for item in data.get("edited", []):
        rows.append(
            f"| {item.get('version', '')} | {item.get('version_label', '')} | {item.get('source_draft_version', '')} | {item.get('mode', '')} | {item.get('fallback_used', '')} | {item.get('json_path', '')} |"
        )
    rows.extend(["", "## Manual Edits", "", "| Version | Label | Source | Mode | Path |", "|---|---|---|---|---|"])
    for item in data.get("manual", []):
        source = f"{item.get('source_origin_type', '')}_v{int(item.get('source_origin_version', 0) or 0):03d}" if item.get("source_origin_type") else ""
        rows.append(
            f"| {item.get('version', '')} | {item.get('version_label', '')} | {source} | {item.get('mode', '')} | {item.get('json_path', '')} |"
        )
    rows.extend([
        "",
        "## Selected",
        "",
        f"- Type: {selected.get('source_type', '') if isinstance(selected, dict) else ''}",
        f"- Version: {selected.get('version', '') if isinstance(selected, dict) else ''}",
        f"- Path: {selected.get('json_path', '') if isinstance(selected, dict) else ''}",
        "",
    ])
    return "\n".join(rows)


def _sync_quality_reports(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    reports_dir = data_path / "quality_reports"
    if not reports_dir.exists():
        warnings.append("缺少可选目录：data/quality_reports")
        return
    for source in sorted(reports_dir.glob("*.md")):
        _copy_markdown(source, project_root / "11_Quality_Reports" / source.name, synced_files, warnings)



def _sync_status_report(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    _copy_markdown(
        data_path / "status" / "latest_status.md",
        project_root / "12_Status" / "Latest_Status.md",
        synced_files,
        warnings,
    )


def _sync_todos(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    _copy_markdown(
        data_path / "todos" / "todos.md",
        project_root / "13_Todos" / "Todos.md",
        synced_files,
        warnings,
    )


def _sync_qa_logs(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    logs_dir = data_path / "qa_logs"
    if not logs_dir.exists():
        warnings.append("缺少可选目录：data/qa_logs")
        return
    for source in sorted(logs_dir.glob("*.md")):
        _copy_markdown(source, project_root / "14_QA_Logs" / source.name, synced_files, warnings)


def _sync_shell_logs(
    data_path: Path,
    project_root: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    config = load_local_config()
    if not config.get("sync_shell_logs_to_obsidian", False):
        return
    logs_dir = data_path / "shell_logs"
    if not logs_dir.exists():
        warnings.append("缺少可选目录：data/shell_logs")
        return
    for source in sorted(logs_dir.glob("*.log")):
        target = project_root / "15_Shell_Logs" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        synced_files.append(target.as_posix())


def _write_index(project_root: Path, synced_files: list[str]) -> str:
    chapter_links = _links_from_dir(project_root / "03_Chapters")
    summary_links = _links_from_dir(project_root / "04_Summaries")
    character_links = _links_from_dir(project_root / "02_Characters")
    manual_links = _links_from_dir(project_root / "10_Manual")
    quality_links = _links_from_dir(project_root / "11_Quality_Reports")
    status_links = _links_from_dir(project_root / "12_Status")
    todo_links = _links_from_dir(project_root / "13_Todos")
    qa_links = _links_from_dir(project_root / "14_QA_Logs")
    shell_links = _links_from_dir(project_root / "15_Shell_Logs", pattern="*.log")
    content = f"""# Story OS 知识库索引

## 项目

- [[Project]]
- [[Story_Spec]]
- [[Story_Blueprint]]
- [[State]]

## 世界观

- [[World_Bible]]

## 角色

- [[Characters]]
{character_links}

## 正文章节

{chapter_links or "暂无"}

## 章节摘要

{summary_links or "暂无"}

## 伏笔

- [[Foreshadows]]

## 时间线

- [[Timeline]]

## 当前计划

- [[Next_Chapter_Plan]]
- [[Current_Context]]

## 质量报告

{quality_links or "暂无"}

## 项目状态

{status_links or "- [[Latest_Status]]"}

## 待办事项

{todo_links or "- [[Todos]]"}

## 问答记录

{qa_links or "暂无"}

## Shell Logs

{shell_links or "未启用同步"}
"""
    index_path = project_root / "99_Index" / "Story_OS_Index.md"
    index_path.write_text(content, encoding="utf-8")
    synced_files.append(index_path.as_posix())
    return index_path.as_posix()


def _copy_markdown(
    source: Path,
    target: Path,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    if not source.exists():
        warnings.append(f"缺少可选文件：{source.as_posix()}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    synced_files.append(target.as_posix())


def _json_to_markdown(
    source: Path,
    target: Path,
    title: str,
    synced_files: list[str],
    warnings: list[str],
) -> None:
    if not source.exists():
        warnings.append(f"缺少可选文件：{source.as_posix()}")
        return
    data = _read_json(source)
    content = f"# {title}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n"
    target.write_text(content, encoding="utf-8")
    synced_files.append(target.as_posix())


def _render_character_markdown(character: dict[str, Any]) -> str:
    state = character.get("current_state", {})
    voice = character.get("voice_profile", {})
    return f"""# {character.get("name", "")}

## 基础信息

- ID：{character.get("id", "")}
- 角色定位：{character.get("role", "")}
- 年龄：{character.get("age", "")}
- 性别：{character.get("gender", "")}

## 外貌

{character.get("appearance", "")}

## 性格

{_join_list(character.get("personality", []))}

## 核心欲望

{character.get("core_desire", "")}

## 核心恐惧

{character.get("core_fear", "")}

## 当前状态

- 身体：{state.get("physical", "")}
- 心理：{state.get("mental", "")}
- 资源：{_join_list(state.get("resources", []))}
- 已知信息：{_join_list(state.get("knowledge", []))}

## 语言风格

- 语气：{voice.get("tone", "")}
- 句长：{voice.get("sentence_length", "")}
- 习惯：{_join_list(voice.get("speech_habits", []))}

## 关系

{json.dumps(character.get("relationships", {}), ensure_ascii=False, indent=2)}
"""


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    chapter_id = summary.get("chapter_id", "")
    return f"""# 第{chapter_id}章摘要

## 短摘要

{summary.get("short_summary", "")}

## 关键事件

{_render_list(summary.get("key_events", []))}

## 登场角色

{_render_list([item.get("name", item.get("id", "")) for item in summary.get("characters_involved", []) if isinstance(item, dict)])}

## 使用的世界规则

{_render_list([item.get("rule", "") for item in summary.get("world_rules_used", []) if isinstance(item, dict)])}

## 新信息

{_render_list(summary.get("new_information", []))}

## 伏笔

{_render_list([item.get("content", "") for item in summary.get("foreshadows_planted", []) if isinstance(item, dict)])}

## 记忆标签

{_render_list(summary.get("memory_tags", []))}
"""


def _render_foreshadows_markdown(foreshadows: Any) -> str:
    rows = ["# 伏笔登记表", "", "| ID | 内容 | 状态 | 引入章节 | 重要性 |", "|---|---|---|---|---|"]
    if isinstance(foreshadows, list):
        for item in foreshadows:
            if isinstance(item, dict):
                rows.append(
                    f"| {item.get('id', '')} | {item.get('content', '')} | {item.get('status', '')} | {item.get('introduced_at', '')} | {item.get('importance', '')} |"
                )
    return "\n".join(rows) + "\n"


def _render_timeline_markdown(timeline: Any) -> str:
    rows = ["# 时间线", "", "| 章节 | 标题 | 事件 | 时间备注 |", "|---|---|---|---|"]
    if isinstance(timeline, list):
        for item in timeline:
            if isinstance(item, dict):
                rows.append(
                    f"| {item.get('chapter_id', '')} | {item.get('chapter_title', item.get('title', ''))} | {item.get('event', '')} | {item.get('time_note', '')} |"
                )
    return "\n".join(rows) + "\n"


def _links_from_dir(directory: Path, pattern: str = "*.md") -> str:
    if not directory.exists():
        return ""
    links = []
    for path in sorted(directory.glob(pattern)):
        if path.name == "Characters.md":
            continue
        links.append(f"- [[{path.stem}]]")
    return "\n".join(links)


def _safe_filename(filename: str) -> str:
    pattern = f"[{re.escape(WINDOWS_INVALID_FILENAME_CHARS)}]"
    return re.sub(pattern, "_", filename).strip() or "untitled.md"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _join_list(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "、".join(str(item) for item in items)


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)
