from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from system.obsidian_binding import MARKER_FILENAME
from system.obsidian_mirror_manifest import (
    MANIFEST_FILENAME,
    MirrorManifest,
    MirrorManifestEntry,
    MirrorManifestStore,
    build_empty_manifest,
    compute_content_hash,
)


class DiffAction(Enum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    STALE = "stale"
    CONFLICT_MODIFIED = "conflict_modified"
    CONFLICT_TYPE = "conflict_type"
    UNSAFE = "unsafe"


class MirrorSyncError(Exception):
    pass


class MirrorSyncUnsafe(MirrorSyncError):
    pass


class MirrorSyncManifestInvalid(MirrorSyncError):
    pass


class MirrorSyncManifestMismatch(MirrorSyncError):
    pass


class MirrorSyncPlan:
    def __init__(self) -> None:
        self.changes: list[dict[str, Any]] = []
        self.summary: dict[str, int] = {
            "create": 0,
            "update": 0,
            "unchanged": 0,
            "stale": 0,
            "conflict_modified": 0,
            "conflict_type": 0,
            "unsafe": 0,
        }

    def add(self, path: str, action: DiffAction, detail: str = "") -> None:
        self.changes.append({"path": path, "action": action.value, "detail": detail})
        self.summary[action.value] += 1


class MirrorSyncService:
    def __init__(self, binding: Any, data_dir: Path) -> None:
        self.binding = binding
        self.data_dir = data_dir
        self.target_dir = binding.target_full_path
        self.manifest_store = MirrorManifestStore(self.target_dir)

    def run(
        self,
        *,
        dry_run: bool = False,
        prune_stale: bool = False,
    ) -> dict[str, Any]:
        old_manifest = self._load_and_validate_manifest()
        expected = self._build_expected_snapshot()
        plan = self._compute_diff(old_manifest, expected)

        if plan.summary["unsafe"] > 0:
            return self._result("rejected", plan, reason="unsafe_paths_detected")

        if not dry_run:
            self._apply(plan, expected, prune_stale=prune_stale)
            new_manifest = self._build_manifest_from_disk(expected, plan, old_manifest)
            self.manifest_store.save(new_manifest)

        return self._result("dry_run" if dry_run else "completed", plan)

    def _load_and_validate_manifest(self) -> MirrorManifest | None:
        manifest = self.manifest_store.load()
        if manifest is None:
            return None

        if manifest.schema_version != "1.0":
            raise MirrorSyncManifestInvalid(
                f"Unsupported manifest schema version: {manifest.schema_version}"
            )

        if not manifest.validate_identity(
            self.binding.binding_id,
            self.binding.project_id,
            self.binding.timeline_id,
        ):
            raise MirrorSyncManifestMismatch(
                "Manifest identity does not match current binding"
            )

        return manifest

    def _build_expected_snapshot(self) -> dict[str, bytes]:
        """Build expected file snapshot from data_dir without writing to disk."""
        snapshot: dict[str, bytes] = {}
        data_path = self.data_dir

        # 00_Project
        self._add_file_from_source(snapshot, data_path / "project.md", "00_Project/Project.md")
        self._add_json_as_markdown(snapshot, data_path / "story_spec.json", "00_Project/Story_Spec.md", "Story Spec")
        self._add_json_as_markdown(snapshot, data_path / "story_blueprint.json", "00_Project/Story_Blueprint.md", "Story Blueprint")
        self._add_json_as_markdown(snapshot, data_path / "state.json", "00_Project/State.md", "State")

        # 01_World
        self._add_file_from_source(snapshot, data_path / "world_bible.md", "01_World/World_Bible.md")
        self._add_json_as_markdown(snapshot, data_path / "world_bible.json", "01_World/World_Bible_Data.md", "World Bible Data")

        # 02_Characters
        self._add_file_from_source(snapshot, data_path / "characters.md", "02_Characters/Characters.md")
        characters_json = data_path / "characters.json"
        if characters_json.exists():
            characters = json.loads(characters_json.read_text(encoding="utf-8"))
            all_chars = characters.get("main_characters", []) + characters.get("supporting_characters", [])
            for character in all_chars:
                if isinstance(character, dict):
                    char_id = character.get("id", "char")
                    char_name = character.get("name", "角色")
                    safe_name = self._safe_filename(f"{char_id}_{char_name}.md")
                    content = self._render_character_markdown(character).encode("utf-8")
                    snapshot[f"02_Characters/{safe_name}"] = content

        # 03_Chapters
        chapters_dir = data_path / "chapters"
        if chapters_dir.exists():
            for source in sorted(chapters_dir.glob("*.md")):
                snapshot[f"03_Chapters/{source.name}"] = source.read_bytes()

        # 04_Summaries
        summaries_dir = data_path / "summaries"
        if summaries_dir.exists():
            for source in sorted(summaries_dir.glob("*.json")):
                summary = json.loads(source.read_text(encoding="utf-8"))
                content = self._render_summary_markdown(summary).encode("utf-8")
                snapshot[f"04_Summaries/{source.stem}.md"] = content

        # 05_Foreshadows + 06_Timeline (from state.json)
        state_path = data_path / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            foreshadows_content = self._render_foreshadows_markdown(state.get("foreshadows", [])).encode("utf-8")
            snapshot["05_Foreshadows/Foreshadows.md"] = foreshadows_content
            timeline_content = self._render_timeline_markdown(state.get("timeline", [])).encode("utf-8")
            snapshot["06_Timeline/Timeline.md"] = timeline_content

        # 07_Plans
        self._add_file_from_source(snapshot, data_path / "next_chapter_plan.md", "07_Plans/Next_Chapter_Plan.md")
        self._add_file_from_source(snapshot, data_path / "context" / "current_context.md", "07_Plans/Current_Context.md")

        # 08_Drafts
        drafts_dir = data_path / "drafts"
        if drafts_dir.exists():
            for source in sorted(drafts_dir.glob("*.md")):
                snapshot[f"08_Drafts/{source.name}"] = source.read_bytes()

        # 09_Edited
        edited_dir = data_path / "edited"
        if edited_dir.exists():
            for source in sorted(edited_dir.glob("*_v*.md")):
                snapshot[f"09_Edited/{source.name}"] = source.read_bytes()

        # 10_Manual
        manual_dir = data_path / "manual"
        if manual_dir.exists():
            for source in sorted(manual_dir.glob("*_v*.md")):
                snapshot[f"10_Manual/{source.name}"] = source.read_bytes()

        # 10_Versions
        versions_dir = data_path / "versions"
        if versions_dir.exists():
            for source in sorted(versions_dir.glob("*.json")):
                data = json.loads(source.read_text(encoding="utf-8"))
                content = self._render_versions_markdown(data).encode("utf-8")
                snapshot[f"10_Versions/{source.stem}.md"] = content

        # 11_Quality_Reports
        reports_dir = data_path / "quality_reports"
        if reports_dir.exists():
            for source in sorted(reports_dir.glob("*.md")):
                snapshot[f"11_Quality_Reports/{source.name}"] = source.read_bytes()

        # 12_Status
        self._add_file_from_source(snapshot, data_path / "status" / "latest_status.md", "12_Status/Latest_Status.md")

        # 13_Todos
        self._add_file_from_source(snapshot, data_path / "todos" / "todos.md", "13_Todos/Todos.md")

        # 14_QA_Logs
        qa_dir = data_path / "qa_logs"
        if qa_dir.exists():
            for source in sorted(qa_dir.glob("*.md")):
                snapshot[f"14_QA_Logs/{source.name}"] = source.read_bytes()

        # 99_Index
        index_content = self._render_index(snapshot).encode("utf-8")
        snapshot["99_Index/Story_OS_Index.md"] = index_content

        return snapshot

    def _add_file_from_source(
        self, snapshot: dict[str, bytes], source: Path, target_rel: str
    ) -> None:
        if source.exists():
            snapshot[target_rel] = source.read_bytes()

    def _add_json_as_markdown(
        self, snapshot: dict[str, bytes], source: Path, target_rel: str, title: str
    ) -> None:
        if source.exists():
            data = json.loads(source.read_text(encoding="utf-8"))
            content = f"# {title}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n"
            snapshot[target_rel] = content.encode("utf-8")

    def _compute_diff(
        self, old_manifest: MirrorManifest | None, expected: dict[str, bytes]
    ) -> MirrorSyncPlan:
        plan = MirrorSyncPlan()
        old_files: dict[str, MirrorManifestEntry] = old_manifest.files if old_manifest else {}

        # Check expected files
        for rel_path, content in expected.items():
            if not self._is_safe_path(rel_path):
                plan.add(rel_path, DiffAction.UNSAFE, "Path validation failed")
                continue

            target_path = self.target_dir / rel_path
            desired_hash = compute_content_hash(content)

            if target_path.exists():
                if not target_path.is_file():
                    plan.add(rel_path, DiffAction.CONFLICT_TYPE, "Not a regular file")
                    continue

                current_hash = compute_content_hash(target_path.read_bytes())

                # Priority 1: target already has the desired content
                # This covers partial sync recovery and first-sync safe takeover
                if current_hash == desired_hash:
                    plan.add(rel_path, DiffAction.UNCHANGED)
                    continue

                old_entry = old_files.get(rel_path)

                # Priority 2: file unchanged since last sync, needs update
                if old_entry and old_entry.content_hash == current_hash:
                    plan.add(rel_path, DiffAction.UPDATE)
                    continue

                # Priority 3: true conflict - user or external modification
                plan.add(rel_path, DiffAction.CONFLICT_MODIFIED, "File modified externally")
            else:
                plan.add(rel_path, DiffAction.CREATE)

        # Check for stale files
        for rel_path in old_files:
            if rel_path in expected:
                continue
            if rel_path in {MARKER_FILENAME, MANIFEST_FILENAME}:
                continue

            target_path = self.target_dir / rel_path
            if not target_path.exists():
                continue

            if not target_path.is_file():
                continue

            current_hash = compute_content_hash(target_path.read_bytes())
            old_entry = old_files[rel_path]

            if old_entry.content_hash == current_hash:
                plan.add(rel_path, DiffAction.STALE)
            else:
                plan.add(rel_path, DiffAction.CONFLICT_MODIFIED, "Stale file modified externally")

        return plan

    def _apply(self, plan: MirrorSyncPlan, expected: dict[str, bytes], *, prune_stale: bool) -> None:
        from system.project_clone_service import ProjectCloneService

        for change in plan.changes:
            rel_path = change["path"]
            action = change["action"]
            target_path = self.target_dir / rel_path

            if action in (DiffAction.CREATE.value, DiffAction.UPDATE.value):
                # Re-verify path safety before each write
                if not self._is_safe_path(rel_path):
                    raise MirrorSyncUnsafe(f"Path became unsafe: {rel_path}")
                for part in target_path.parents:
                    if part == self.target_dir:
                        break
                    if ProjectCloneService._is_link_or_reparse_point(part):
                        raise MirrorSyncUnsafe(f"Path chain contains link: {part}")

                content = expected[rel_path]
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(content)

            elif action == DiffAction.STALE.value and prune_stale:
                if not self._is_safe_path(rel_path):
                    raise MirrorSyncUnsafe(f"Path became unsafe: {rel_path}")
                if ProjectCloneService._is_link_or_reparse_point(target_path):
                    raise MirrorSyncUnsafe(f"Cannot delete link: {rel_path}")
                if target_path.exists() and target_path.is_file():
                    target_path.unlink()

    def _build_manifest_from_disk(
        self, expected: dict[str, bytes], plan: MirrorSyncPlan, old_manifest: MirrorManifest | None
    ) -> MirrorManifest:
        manifest = build_empty_manifest(
            self.binding.binding_id,
            self.binding.project_id,
            self.binding.timeline_id,
        )
        now = datetime.now(timezone.utc).isoformat()

        conflict_paths = {
            c["path"] for c in plan.changes
            if c["action"] in (DiffAction.CONFLICT_MODIFIED.value, DiffAction.CONFLICT_TYPE.value)
        }

        for rel_path in expected:
            if rel_path in conflict_paths:
                # Preserve old manifest entry for conflict files
                if old_manifest and rel_path in old_manifest.files:
                    manifest.files[rel_path] = old_manifest.files[rel_path]
                continue

            target_path = self.target_dir / rel_path
            if target_path.exists() and target_path.is_file():
                content = target_path.read_bytes()
                manifest.files[rel_path] = MirrorManifestEntry(
                    source_id=rel_path,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content),
                    last_synced_at=now,
                )

        return manifest

    def _is_safe_path(self, rel_path: str) -> bool:
        from system.obsidian_path_validator import ObsidianPathValidator
        ok, _ = ObsidianPathValidator.validate_target_relative_path(rel_path)
        if not ok:
            return False
        target = self.target_dir / rel_path
        try:
            target.relative_to(self.target_dir.resolve())
        except ValueError:
            return False
        return True

    def _result(self, status: str, plan: MirrorSyncPlan, reason: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": status,
            "project_id": self.binding.project_id,
            "timeline_id": self.binding.timeline_id,
            "binding_id": self.binding.binding_id,
            "summary": plan.summary,
            "changes": plan.changes,
        }
        if reason:
            result["reason"] = reason
        return result

    # Rendering helpers (mirroring obsidian_sync.py)
    def _safe_filename(self, filename: str) -> str:
        import re
        invalid = r'<>\:"/\\|?*'
        return re.sub(f"[{re.escape(invalid)}]", "_", filename).strip() or "untitled.md"

    def _render_character_markdown(self, character: dict[str, Any]) -> str:
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

{self._join_list(character.get("personality", []))}

## 核心欲望

{character.get("core_desire", "")}

## 核心恐惧

{character.get("core_fear", "")}

## 当前状态

- 身体：{state.get("physical", "")}
- 心理：{state.get("mental", "")}
- 资源：{self._join_list(state.get("resources", []))}
- 已知信息：{self._join_list(state.get("knowledge", []))}

## 语言风格

- 语气：{voice.get("tone", "")}
- 句长：{voice.get("sentence_length", "")}
- 习惯：{self._join_list(voice.get("speech_habits", []))}

## 关系

{json.dumps(character.get("relationships", {}), ensure_ascii=False, indent=2)}
"""

    def _render_summary_markdown(self, summary: dict[str, Any]) -> str:
        chapter_id = summary.get("chapter_id", "")
        return f"""# 第{chapter_id}章摘要

## 短摘要

{summary.get("short_summary", "")}

## 关键事件

{self._render_list(summary.get("key_events", []))}

## 登场角色

{self._render_list([item.get("name", item.get("id", "")) for item in summary.get("characters_involved", []) if isinstance(item, dict)])}

## 使用的世界规则

{self._render_list([item.get("rule", "") for item in summary.get("world_rules_used", []) if isinstance(item, dict)])}

## 新信息

{self._render_list(summary.get("new_information", []))}

## 伏笔

{self._render_list([item.get("content", "") for item in summary.get("foreshadows_planted", []) if isinstance(item, dict)])}

## 记忆标签

{self._render_list(summary.get("memory_tags", []))}
"""

    def _render_foreshadows_markdown(self, foreshadows: Any) -> str:
        rows = ["# 伏笔登记表", "", "| ID | 内容 | 状态 | 引入章节 | 重要性 |", "|---|---|---|---|---|"]
        if isinstance(foreshadows, list):
            for item in foreshadows:
                if isinstance(item, dict):
                    rows.append(
                        f"| {item.get('id', '')} | {item.get('content', '')} | {item.get('status', '')} | {item.get('introduced_at', '')} | {item.get('importance', '')} |"
                    )
        return "\n".join(rows) + "\n"

    def _render_timeline_markdown(self, timeline: Any) -> str:
        rows = ["# 时间线", "", "| 章节 | 标题 | 事件 | 时间备注 |", "|---|---|---|---|"]
        if isinstance(timeline, list):
            for item in timeline:
                if isinstance(item, dict):
                    rows.append(
                        f"| {item.get('chapter_id', '')} | {item.get('chapter_title', item.get('title', ''))} | {item.get('event', '')} | {item.get('time_note', '')} |"
                    )
        return "\n".join(rows) + "\n"

    def _render_versions_markdown(self, data: dict[str, Any]) -> str:
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

    def _render_index(self, snapshot: dict[str, bytes]) -> str:
        def _links(prefix: str) -> str:
            paths = [p for p in snapshot if p.startswith(prefix) and p.endswith(".md")]
            links = []
            for p in sorted(paths):
                name = Path(p).stem
                if name != "Characters":
                    links.append(f"- [[{name}]]")
            return "\n".join(links) or "暂无"

        return f"""# Story OS 知识库索引

## 项目

- [[Project]]
- [[Story_Spec]]
- [[Story_Blueprint]]
- [[State]]

## 世界观

- [[World_Bible]]

## 角色

- [[Characters]]
{_links("02_Characters/")}

## 正文章节

{_links("03_Chapters/")}

## 章节摘要

{_links("04_Summaries/")}

## 伏笔

- [[Foreshadows]]

## 时间线

- [[Timeline]]

## 当前计划

- [[Next_Chapter_Plan]]
- [[Current_Context]]

## 质量报告

{_links("11_Quality_Reports/")}

## 项目状态

- [[Latest_Status]]

## 待办事项

- [[Todos]]

## 问答记录

{_links("14_QA_Logs/")}

## Shell Logs

未启用同步
"""

    def _join_list(self, items: Any) -> str:
        if not isinstance(items, list):
            return ""
        return "、".join(str(item) for item in items)

    def _render_list(self, items: Any) -> str:
        if not isinstance(items, list) or not items:
            return "无"
        return "\n".join(f"- {item}" for item in items)