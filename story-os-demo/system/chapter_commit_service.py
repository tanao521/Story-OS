from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.commit_run_store import CommitRun, CommitRunStore, PostCommitTaskState
from system.data_store import DataStore, DataWriteError
from system.revision_service import RevisionService


class PostCommitPolicy(str, Enum):
    FULL = "full"
    LOCAL_ONLY = "local_only"
    DEFERRED = "deferred"


class CommitStatus(str, Enum):
    COMMITTED = "committed"
    ALREADY_COMMITTED = "already_committed"
    COMMITTED_WITH_WARNINGS = "committed_with_warnings"
    FAILED = "failed"


class SourceType(str, Enum):
    SELECTED = "selected"
    MANUAL = "manual"
    EDITED = "edited"
    DRAFT = "draft"


@dataclass
class CommitResult:
    status: CommitStatus
    project_id: str
    chapter_id: int
    commit_id: str
    source_type: SourceType
    source_version_id: str | None
    source_hash: str
    canon_revision_id: str | None
    chapter_path: str | None
    summary_path: str | None
    source_path: str | None = None
    core_commit: dict[str, str] = field(default_factory=dict)
    post_commit: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ChapterCommitService:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.data_store = DataStore(context)
        self.revision_service = RevisionService(context)
        self.run_store = CommitRunStore(context)
        self._lock = type("Lock", (), {"__enter__": lambda self: None, "__exit__": lambda *args: None})()

    def commit_chapter(
        self,
        chapter_id: int,
        source_version_id: str | None = None,
        post_commit_policy: PostCommitPolicy = PostCommitPolicy.LOCAL_ONLY,
    ) -> CommitResult:
        with self._lock:
            return self._do_commit(chapter_id, source_version_id, post_commit_policy)

    def _do_commit(
        self,
        chapter_id: int,
        source_version_id: str | None,
        post_commit_policy: PostCommitPolicy,
    ) -> CommitResult:
        project_id = self.context.root.name or "default"

        try:
            phase_a = self._phase_a_preflight(chapter_id)
            if phase_a.status != "passed":
                return CommitResult(
                    status=CommitStatus.FAILED,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    commit_id="",
                    source_type=SourceType.DRAFT,
                    source_version_id=None,
                    source_hash="",
                    canon_revision_id=None,
                    chapter_path=None,
                    summary_path=None,
                    warnings=[f"Preflight failed: {phase_a.reason}"],
                )

            phase_b = self._phase_b_source_resolution(chapter_id, source_version_id)
            if phase_b.status != "resolved":
                return CommitResult(
                    status=CommitStatus.FAILED,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    commit_id="",
                    source_type=phase_b.source_type,
                    source_version_id=None,
                    source_hash="",
                    canon_revision_id=None,
                    chapter_path=None,
                    summary_path=None,
                    warnings=[f"Source resolution failed: {phase_b.reason}"],
                )

            commit_key = self._generate_commit_key(project_id, chapter_id, phase_b)
            existing_run = self._check_idempotency(commit_key, phase_b.source_hash, chapter_id)
            if existing_run:
                return self._handle_existing_run(existing_run, phase_b, post_commit_policy)

            phase_c = self._phase_c_prepare(chapter_id, phase_b)
            snapshot = self._create_snapshot(chapter_id)

            # Create commit run record before core commit
            commit_run = CommitRun(
                commit_id=commit_key,
                project_id=project_id,
                chapter_id=chapter_id,
                source_hash=phase_b.source_hash,
                source_version_id=phase_b.source_version_id,
                post_commit_policy=post_commit_policy.value,
            )

            try:
                phase_d = self._phase_d_core_commit(chapter_id, phase_c, commit_key)
            except Exception as exc:
                self._rollback_snapshot(chapter_id, snapshot)
                commit_run.status = "failed"
                commit_run.warnings.append(f"Core commit failed: {str(exc)}")
                self.run_store.save(commit_run)
                return CommitResult(
                    status=CommitStatus.FAILED,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    commit_id=commit_key,
                    source_type=phase_b.source_type,
                    source_version_id=phase_b.source_version_id,
                    source_hash=phase_b.source_hash,
                    canon_revision_id=None,
                    chapter_path=None,
                    summary_path=None,
                    core_commit=phase_c.core_commit if phase_c.core_commit else {},
                    warnings=[f"Core commit failed: {str(exc)}"],
                )

            # Core commit succeeded, update run record
            commit_run.status = "core_committed"
            commit_run.canon_revision_id = phase_d.canon_revision_id
            commit_run.chapter_path = phase_d.chapter_path
            commit_run.summary_path = phase_d.summary_path
            commit_run.core_commit = phase_d.core_commit
            self.run_store.save(commit_run)

            if post_commit_policy != PostCommitPolicy.DEFERRED:
                phase_e = self._phase_e_post_commit(chapter_id, phase_c, post_commit_policy, commit_run)
            else:
                phase_e = self._mark_deferred(commit_run)

            all_warnings = list(phase_b.warnings)
            all_warnings.extend(phase_c.warnings)
            if phase_e.get("warnings"):
                all_warnings.extend(phase_e["warnings"])

            if phase_e.get("failed") and all_warnings:
                status = CommitStatus.COMMITTED_WITH_WARNINGS
                commit_run.status = "completed_with_warnings"
            else:
                status = CommitStatus.COMMITTED
                commit_run.status = "completed"

            commit_run.warnings.extend(all_warnings)
            self.run_store.save(commit_run)

            return CommitResult(
                status=status,
                project_id=project_id,
                chapter_id=chapter_id,
                commit_id=commit_key,
                source_type=phase_b.source_type,
                source_version_id=phase_b.source_version_id,
                source_hash=phase_b.source_hash,
                canon_revision_id=phase_d.canon_revision_id,
                chapter_path=phase_d.chapter_path,
                summary_path=phase_d.summary_path,
                source_path=phase_b.source_path,
                core_commit=phase_d.core_commit,
                post_commit=phase_e.get("post_commit", {}),
                warnings=all_warnings,
            )

        except Exception as exc:
            return CommitResult(
                status=CommitStatus.FAILED,
                project_id=project_id,
                chapter_id=chapter_id,
                commit_id="",
                source_type=SourceType.DRAFT,
                source_version_id=None,
                source_hash="",
                canon_revision_id=None,
                chapter_path=None,
                summary_path=None,
                warnings=[f"Unexpected error: {str(exc)}"],
            )

    @dataclass
    class PreflightResult:
        status: str
        reason: str = ""

    def _phase_a_preflight(self, chapter_id: int) -> PreflightResult:
        if chapter_id < 1:
            return self.PreflightResult(status="failed", reason="Invalid chapter ID")
        if not self.context.root.exists():
            return self.PreflightResult(status="failed", reason="Project context root does not exist")
        return self.PreflightResult(status="passed")

    @dataclass
    class SourceResolutionResult:
        status: str
        source_type: SourceType
        source_version_id: str | None
        source_hash: str
        content: str
        chapter_title: str
        source_path: str | None = None
        reason: str = ""
        warnings: list[str] = field(default_factory=list)

    def _phase_b_source_resolution(
        self, chapter_id: int, source_version_id: str | None
    ) -> SourceResolutionResult:
        if source_version_id:
            version = self._load_version_by_id(source_version_id)
            if version:
                content = str(version.get("content", version.get("draft_text", version.get("edited_text", ""))))
                content_hash = self._hash_content(content)
                return self.SourceResolutionResult(
                    status="resolved",
                    source_type=self._detect_source_type(version),
                    source_version_id=source_version_id,
                    source_hash=content_hash,
                    content=content,
                    chapter_title=str(version.get("chapter_title", f"第{chapter_id}章")),
                    source_path=str(version.get("source_path", "")),
                )

        # Check standalone selected version file
        selected_path = self.context.root / "data" / "versions" / f"chapter_{chapter_id:03d}_selected.json"
        if selected_path.exists():
            try:
                data = json.loads(selected_path.read_text(encoding="utf-8"))
                content = str(data.get("content", data.get("manual_text", data.get("edited_text", data.get("draft_text", "")))))
                if content.strip():
                    content_hash = self._hash_content(content)
                    return self.SourceResolutionResult(
                        status="resolved",
                        source_type=SourceType.SELECTED,
                        source_version_id=f"chapter_{chapter_id:03d}_selected.json",
                        source_hash=content_hash,
                        content=content,
                        chapter_title=str(data.get("chapter_title", f"第{chapter_id}章")),
                        source_path=str(selected_path.relative_to(self.context.root)),
                    )
            except (OSError, json.JSONDecodeError):
                pass

        # Check selected version from versions index
        versions_path = self.context.root / "data" / "versions" / f"chapter_{chapter_id:03d}_versions.json"
        selected_missing_warning = ""
        if versions_path.exists():
            try:
                versions_data = json.loads(versions_path.read_text(encoding="utf-8"))
                selected = versions_data.get("selected")
                if selected:
                    source_type = selected.get("source_type", "draft")
                    version = selected.get("version", 1)
                    version_label = selected.get("version_label", f"{source_type}_v{version:03d}")
                    json_path = selected.get("json_path", "")
                    if json_path:
                        source_file = self.context.root / json_path
                    else:
                        source_file = self.context.root / "data" / source_type / f"chapter_{chapter_id:03d}_{version_label}.json"
                    if source_file.exists():
                        data = json.loads(source_file.read_text(encoding="utf-8"))
                        content = str(data.get("content", data.get("manual_text", data.get("edited_text", data.get("draft_text", "")))))
                        if content.strip():
                            content_hash = self._hash_content(content)
                            return self.SourceResolutionResult(
                                status="resolved",
                                source_type=SourceType(source_type),
                                source_version_id=version_label,
                                source_hash=content_hash,
                                content=content,
                                chapter_title=str(data.get("chapter_title", f"第{chapter_id}章")),
                                source_path=str(source_file.relative_to(self.context.root)),
                            )
                    selected_missing_warning = f"Selected version {version_label} not found at {source_file.name}; falling back."
            except (OSError, json.JSONDecodeError):
                pass

        paths = [
            ("manual", Path("data/manual") / f"chapter_{chapter_id:03d}_manual_v*.json"),
            ("edited", Path("data/edited") / f"chapter_{chapter_id:03d}_edited_v*.json"),
            ("draft", Path("data/drafts") / f"chapter_{chapter_id:03d}_draft_v*.json"),
        ]

        warnings = [selected_missing_warning] if selected_missing_warning else []
        for source_type, pattern in paths:
            resolved_path = self.context.root / pattern
            matches = list(resolved_path.parent.glob(resolved_path.name)) if "*" in str(pattern) else [resolved_path]
            if matches:
                latest = sorted(matches, key=lambda p: p.name)[-1]
                try:
                    data = json.loads(latest.read_text(encoding="utf-8"))
                    content = str(data.get("content", data.get("manual_text", data.get("edited_text", data.get("draft_text", "")))))
                    if content.strip():
                        content_hash = self._hash_content(content)
                        return self.SourceResolutionResult(
                            status="resolved",
                            source_type=SourceType(source_type),
                            source_version_id=str(latest.name),
                            source_hash=content_hash,
                            content=content,
                            chapter_title=str(data.get("chapter_title", f"第{chapter_id}章")),
                            source_path=str(latest.relative_to(self.context.root)),
                            warnings=warnings,
                        )
                except (OSError, json.JSONDecodeError):
                    continue

        return self.SourceResolutionResult(
            status="failed",
            source_type=SourceType.DRAFT,
            source_version_id=None,
            source_hash="",
            content="",
            chapter_title=f"第{chapter_id}章",
            reason="No valid source version found",
        )

    def _load_version_by_id(self, version_id: str) -> dict[str, Any] | None:
        patterns = [
            Path("data/versions") / version_id,
            Path("data/manual") / version_id,
            Path("data/edited") / version_id,
            Path("data/drafts") / version_id,
        ]
        for pattern in patterns:
            path = self.context.root / pattern
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
        return None

    def _detect_source_type(self, version: dict[str, Any]) -> SourceType:
        if version.get("manual_text"):
            return SourceType.MANUAL
        if version.get("edited_text"):
            return SourceType.EDITED
        return SourceType.DRAFT

    def _hash_content(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _generate_commit_key(self, project_id: str, chapter_id: int, phase_b: SourceResolutionResult) -> str:
        key = f"{project_id}:{chapter_id}:{phase_b.source_hash}:{phase_b.source_version_id or ''}:commit"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _check_idempotency(self, commit_key: str, source_hash: str, chapter_id: int) -> CommitRun | None:
        # 1. Check persistent commit run store first (cross-process)
        run = self.run_store.load(commit_key)
        if run and run.source_hash == source_hash:
            return run
        run = self.run_store.find_by_chapter_and_hash(chapter_id, source_hash)
        if run:
            return run
        # 2. Fallback to state.json (backward compat)
        try:
            state = self.data_store.read_json("data/state.json", default={})
            last_commit = state.get("last_committed_chapter", {})
            if last_commit.get("commit_id") == commit_key:
                return None  # Legacy path, no run record
            if last_commit.get("source_hash") == source_hash and last_commit.get("chapter_id") == self._current_chapter_from_state(state):
                return None
        except Exception:
            pass
        return None

    def _current_chapter_from_state(self, state: dict[str, Any]) -> int | None:
        return state.get("current_chapter")

    @dataclass
    class PrepareResult:
        chapter_markdown: str
        summary: dict[str, Any]
        state: dict[str, Any]
        memory_index: dict[str, Any]
        canon_metadata: dict[str, Any]
        core_commit: dict[str, str] = field(default_factory=dict)
        warnings: list[str] = field(default_factory=list)

    def _phase_c_prepare(self, chapter_id: int, phase_b: SourceResolutionResult) -> PrepareResult:
        chapter_markdown = f"# 第{chapter_id}章 {phase_b.chapter_title}\n\n{phase_b.content}\n"

        summary = {
            "summary_version": "1.2",
            "chapter_id": chapter_id,
            "chapter_title": phase_b.chapter_title,
            "short_summary": f"《{phase_b.chapter_title}》的正式章节内容。",
            "key_events": [],
            "characters_involved": [],
            "world_rules_used": [],
            "new_information": [],
            "foreshadows_planted": [],
            "foreshadows_touched": [],
            "state_changes": {"characters": {}, "world": {}, "plot": {}, "timeline": []},
            "memory_tags": ["chapter", "committed"],
        }

        state = self.data_store.read_json("data/state.json", default={})
        state["current_chapter"] = chapter_id
        state["current_stage"] = "chapter_committed"
        state.setdefault("plot", {}).setdefault("completed_events", []).append(f"第{chapter_id}章已提交")
        state["last_committed_chapter"] = {
            "chapter_id": chapter_id,
            "title": phase_b.chapter_title,
            "chapter_path": self._chapter_path(chapter_id).as_posix(),
            "summary_path": self._summary_path(chapter_id).as_posix(),
            "commit_id": "",
            "source_hash": phase_b.source_hash,
        }

        memory_index = self.data_store.read_json("data/memory/memory_index.json", default={})
        memory_index.setdefault("memory_version", "0.6")
        memory_index.setdefault("working_context_chapters", 3)
        chapters = memory_index.setdefault("chapters", [])
        chapter_entry = {
            "chapter_id": chapter_id,
            "title": phase_b.chapter_title,
            "chapter_path": self._chapter_path(chapter_id).as_posix(),
            "summary_path": self._summary_path(chapter_id).as_posix(),
            "memory_tags": summary["memory_tags"],
            "short_summary": summary["short_summary"],
        }
        for i, existing in enumerate(chapters):
            if existing.get("chapter_id") == chapter_id:
                chapters[i] = chapter_entry
                break
        else:
            chapters.append(chapter_entry)

        canon_metadata = {
            "chapter_id": chapter_id,
            "title": phase_b.chapter_title,
            "source_type": phase_b.source_type.value,
            "source_version_id": phase_b.source_version_id,
            "source_hash": phase_b.source_hash,
        }

        warnings = []
        if self._chapter_path(chapter_id).exists():
            warnings.append("正式章节文件已存在，本次将覆盖。")

        return self.PrepareResult(
            chapter_markdown=chapter_markdown,
            summary=summary,
            state=state,
            memory_index=memory_index,
            canon_metadata=canon_metadata,
            warnings=warnings,
        )

    def _create_snapshot(self, chapter_id: int) -> dict[str, str | None]:
        snapshot = {}
        for rel_path in [
            f"data/chapters/chapter_{chapter_id:03d}.md",
            f"data/summaries/chapter_{chapter_id:03d}_summary.json",
            "data/state.json",
            "data/memory/memory_index.json",
            f"data/canon_versions/chapter_{chapter_id:03d}/canon_index.json",
        ]:
            abs_path = self.context.root / rel_path
            if abs_path.exists():
                try:
                    snapshot[rel_path] = abs_path.read_text(encoding="utf-8")
                except OSError:
                    snapshot[rel_path] = None
            else:
                snapshot[rel_path] = None
        return snapshot

    def _rollback_snapshot(self, chapter_id: int, snapshot: dict[str, str | None]) -> None:
        for rel_path, content in snapshot.items():
            abs_path = self.context.root / rel_path
            if content is not None:
                try:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(content, encoding="utf-8")
                except OSError:
                    pass
            elif abs_path.exists():
                try:
                    abs_path.unlink()
                except OSError:
                    pass

        # Clean up orphan canon revision files not referenced by canon_index
        canon_dir = self.context.root / f"data/canon_versions/chapter_{chapter_id:03d}"
        if canon_dir.exists():
            index_path = canon_dir / "canon_index.json"
            referenced = set()
            if index_path.exists():
                try:
                    index_data = self.data_store.read_json(
                        f"data/canon_versions/chapter_{chapter_id:03d}/canon_index.json", default={}
                    )
                    for v in index_data.get("versions", []):
                        content_path = v.get("content_path", "")
                        if content_path:
                            referenced.add(Path(content_path).name)
                except Exception:
                    pass
            for f in canon_dir.iterdir():
                if f.name != "canon_index.json" and f.name not in referenced:
                    try:
                        f.unlink()
                    except OSError:
                        pass

    @dataclass
    class CoreCommitResult:
        canon_revision_id: str | None
        chapter_path: str
        summary_path: str
        core_commit: dict[str, str]

    def _phase_d_core_commit(
        self, chapter_id: int, phase_c: PrepareResult, commit_key: str
    ) -> CoreCommitResult:
        core_commit = {}

        phase_c.state["last_committed_chapter"]["commit_id"] = commit_key

        canon_revision = self.revision_service.create_and_apply_revision(
            chapter_id,
            phase_c.chapter_markdown,
            phase_c.canon_metadata,
        )
        core_commit["canon_revision"] = "success" if canon_revision else "failed"
        canon_revision_id = canon_revision.get("revision_id") if canon_revision else None

        self.data_store.write_markdown(self._chapter_path(chapter_id), phase_c.chapter_markdown)
        core_commit["chapter_projection"] = "success"

        self.data_store.write_json(self._summary_path(chapter_id), phase_c.summary)
        core_commit["summary"] = "success"

        self.data_store.write_json("data/state.json", phase_c.state, backup=True)
        core_commit["state"] = "success"

        self.data_store.write_json("data/memory/memory_index.json", phase_c.memory_index)
        core_commit["memory_index"] = "success"

        return self.CoreCommitResult(
            canon_revision_id=canon_revision_id,
            chapter_path=self._chapter_path(chapter_id).as_posix(),
            summary_path=self._summary_path(chapter_id).as_posix(),
            core_commit=core_commit,
        )

    def _phase_e_post_commit(
        self, chapter_id: int, phase_c: PrepareResult, policy: PostCommitPolicy,
        commit_run: CommitRun | None = None, only_tasks: list[str] | None = None
    ) -> dict[str, Any]:
        post_commit = {}
        warnings = []
        failed = []

        def _run_task(name: str, fn, *args) -> str:
            if only_tasks is not None and name not in only_tasks:
                return "skipped"
            result = fn(*args)
            if commit_run is not None:
                task_state = commit_run.post_commit.get(name, PostCommitTaskState())
                task_state.attempts += 1
                task_state.completed_at = datetime.now(timezone.utc).isoformat()
                if result == "success":
                    task_state.status = "success"
                    task_state.last_error = None
                else:
                    task_state.status = "failed"
                    task_state.last_error = result
                commit_run.post_commit[name] = task_state
                self.run_store.save(commit_run)
            return result

        post_commit["context_refresh"] = _run_task("context_refresh", self._refresh_context, chapter_id, phase_c)
        if post_commit["context_refresh"] != "success":
            warnings.append(f"Context refresh: {post_commit['context_refresh']}")

        # chroma_index is a required local side-effect for both LOCAL_ONLY and FULL.
        if policy in (PostCommitPolicy.LOCAL_ONLY, PostCommitPolicy.FULL):
            post_commit["chroma_index"] = _run_task("chroma_index", self._index_chroma, chapter_id)
            if post_commit["chroma_index"] != "success":
                warnings.append(f"Chroma index: {post_commit['chroma_index']}")
                failed.append("chroma_index")

        if policy == PostCommitPolicy.FULL:
            post_commit["version_archive"] = _run_task("version_archive", self._archive_work_versions, chapter_id)
            if post_commit["version_archive"] != "success":
                warnings.append(f"Version archive: {post_commit['version_archive']}")

            post_commit["obsidian_sync"] = _run_task("obsidian_sync", self._sync_obsidian, chapter_id)
            if post_commit["obsidian_sync"] != "success":
                warnings.append(f"Obsidian sync: {post_commit['obsidian_sync']}")
                failed.append("obsidian_sync")

            post_commit["reflection_job"] = _run_task("reflection_job", self._create_reflection_job, chapter_id)
            if post_commit["reflection_job"] != "success":
                warnings.append(f"Reflection job: {post_commit['reflection_job']}")

            post_commit["planning_anchor"] = _run_task("planning_anchor", self._update_planning_anchor, chapter_id)
            if post_commit["planning_anchor"] != "success":
                warnings.append(f"Planning anchor: {post_commit['planning_anchor']}")

        return {
            "status": "completed_with_warnings" if warnings else "completed",
            "post_commit": post_commit,
            "warnings": warnings,
            "failed": failed,
        }

    def _handle_existing_run(self, run: CommitRun, phase_b: SourceResolutionResult, policy: PostCommitPolicy) -> CommitResult:
        # If core not completed, treat as new attempt (should not happen normally)
        if run.status == "failed":
            return CommitResult(
                status=CommitStatus.FAILED,
                project_id=run.project_id,
                chapter_id=run.chapter_id,
                commit_id=run.commit_id,
                source_type=phase_b.source_type,
                source_version_id=phase_b.source_version_id,
                source_hash=phase_b.source_hash,
                canon_revision_id=run.canon_revision_id,
                chapter_path=run.chapter_path,
                summary_path=run.summary_path,
                source_path=phase_b.source_path,
                warnings=run.warnings or ["Previous commit failed"],
            )

        # Core completed. Check if we need post-commit compensation.
        pending = run.pending_tasks(policy.value)
        if pending and policy != PostCommitPolicy.DEFERRED:
            # Re-run only pending/failed tasks
            result = self._resume_post_commit_from_run(run, policy)
            return result

        if run.status in ("completed", "completed_with_warnings") or run.all_tasks_success(policy.value):
            return CommitResult(
                status=CommitStatus.ALREADY_COMMITTED,
                project_id=run.project_id,
                chapter_id=run.chapter_id,
                commit_id=run.commit_id,
                source_type=phase_b.source_type,
                source_version_id=phase_b.source_version_id,
                source_hash=phase_b.source_hash,
                canon_revision_id=run.canon_revision_id,
                chapter_path=run.chapter_path,
                summary_path=run.summary_path,
                source_path=phase_b.source_path,
                core_commit=run.core_commit,
                post_commit={k: v.status for k, v in run.post_commit.items()},
                warnings=["Already committed with same content"],
            )

        # Default: return already committed
        return CommitResult(
            status=CommitStatus.ALREADY_COMMITTED,
            project_id=run.project_id,
            chapter_id=run.chapter_id,
            commit_id=run.commit_id,
            source_type=phase_b.source_type,
            source_version_id=phase_b.source_version_id,
            source_hash=phase_b.source_hash,
            canon_revision_id=run.canon_revision_id,
            chapter_path=run.chapter_path,
            summary_path=run.summary_path,
            source_path=phase_b.source_path,
            core_commit=run.core_commit,
            post_commit={k: v.status for k, v in run.post_commit.items()},
            warnings=["Already committed with same content"],
        )

    def resume_post_commit(self, commit_id: str, policy: PostCommitPolicy | None = None) -> CommitResult:
        run = self.run_store.load(commit_id)
        if not run:
            return CommitResult(
                status=CommitStatus.FAILED,
                project_id=self.context.root.name or "default",
                chapter_id=0,
                commit_id=commit_id,
                source_type=SourceType.DRAFT,
                source_version_id=None,
                source_hash="",
                canon_revision_id=None,
                chapter_path=None,
                summary_path=None,
                warnings=[f"Commit run not found: {commit_id}"],
            )
        effective_policy = policy if policy is not None else PostCommitPolicy(run.post_commit_policy)
        return self._resume_post_commit_from_run(run, effective_policy)

    def _resume_post_commit_from_run(self, run: CommitRun, policy: PostCommitPolicy) -> CommitResult:
        pending = run.pending_tasks(policy.value)
        if not pending:
            return CommitResult(
                status=CommitStatus.ALREADY_COMMITTED,
                project_id=run.project_id,
                chapter_id=run.chapter_id,
                commit_id=run.commit_id,
                source_type=SourceType.DRAFT,
                source_version_id=run.source_version_id,
                source_hash=run.source_hash,
                canon_revision_id=run.canon_revision_id,
                chapter_path=run.chapter_path,
                summary_path=run.summary_path,
                core_commit=run.core_commit,
                post_commit={k: v.status for k, v in run.post_commit.items()},
                warnings=["No pending post-commit tasks"],
            )

        # Build minimal phase_c for post-commit tasks
        phase_c = self.PrepareResult(
            chapter_markdown="",
            summary={"chapter_title": f"第{run.chapter_id}章"},
            state={},
            memory_index={},
            canon_metadata={},
        )

        phase_e = self._phase_e_post_commit(run.chapter_id, phase_c, policy, run, only_tasks=pending)

        run.warnings.extend(phase_e.get("warnings", []))
        if phase_e.get("failed"):
            run.status = "completed_with_warnings"
        else:
            run.status = "completed"
        self.run_store.save(run)

        status = CommitStatus.COMMITTED_WITH_WARNINGS if phase_e.get("failed") else CommitStatus.COMMITTED
        return CommitResult(
            status=status,
            project_id=run.project_id,
            chapter_id=run.chapter_id,
            commit_id=run.commit_id,
            source_type=SourceType.DRAFT,
            source_version_id=run.source_version_id,
            source_hash=run.source_hash,
            canon_revision_id=run.canon_revision_id,
            chapter_path=run.chapter_path,
            summary_path=run.summary_path,
            core_commit=run.core_commit,
            post_commit=phase_e.get("post_commit", {}),
            warnings=phase_e.get("warnings", []),
        )

    def _mark_deferred(self, commit_run: CommitRun) -> dict[str, Any]:
        commit_run.status = "core_committed"
        for name in ["context_refresh", "version_archive", "obsidian_sync",
                     "chroma_index", "reflection_job", "planning_anchor"]:
            commit_run.post_commit[name] = PostCommitTaskState(status="deferred")
        self.run_store.save(commit_run)
        return {
            "status": "deferred",
            "post_commit": {name: "deferred" for name in
                            ["context_refresh", "version_archive", "obsidian_sync",
                             "chroma_index", "reflection_job", "planning_anchor"]},
            "warnings": [],
            "failed": [],
        }

    def _refresh_context(self, chapter_id: int, phase_c: PrepareResult) -> str:
        try:
            self.data_store.write_json("data/context/current_context.json", {
                "chapter_id": chapter_id,
                "chapter_title": phase_c.summary["chapter_title"],
                "summary": phase_c.summary["short_summary"],
            })
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _archive_work_versions(self, chapter_id: int) -> str:
        try:
            from system.version_manager import VersionManager
            vm = VersionManager(self.context.root)
            vm.archive_chapter_versions(chapter_id)
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _sync_obsidian(self, chapter_id: int) -> str:
        try:
            from system.obsidian_sync import sync_to_obsidian
            sync_to_obsidian()
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _index_chroma(self, chapter_id: int) -> str:
        try:
            from system.vector_index_lifecycle import index_chapter, index_summary
            from system.data_store import DataStore
            store = DataStore(self.context)
            chapter_path = self._chapter_path(chapter_id)
            if chapter_path.exists():
                chapter_text = chapter_path.read_text(encoding="utf-8")
                index_chapter(
                    self.context,
                    chapter_id,
                    chapter_text,
                    canon_revision_id=self.revision_service.active_canon(chapter_id).get("canon_version_id"),
                    timeline_id="main",
                )
            summary_path = self._summary_path(chapter_id)
            if summary_path.exists():
                summary_data = store.read_json(summary_path, default={})
                snippet = str(summary_data.get("short_summary", ""))
                tags = " ".join(str(t) for t in summary_data.get("memory_tags", []) if isinstance(t, str))
                events = " ".join(str(e) for e in summary_data.get("key_events", []) if isinstance(e, str))
                summary_text = f"摘要: {snippet}\n标签: {tags}\n事件: {events}"
                if summary_text.strip() and summary_text.strip() not in {"摘要: ", "摘要: \n标签: \n事件: "}:
                    index_summary(
                        self.context,
                        chapter_id,
                        summary_text,
                        canon_revision_id=self.revision_service.active_canon(chapter_id).get("canon_version_id"),
                        timeline_id="main",
                    )
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _create_reflection_job(self, chapter_id: int) -> str:
        try:
            from system.job_manager import create_job
            create_job("chapter_reflection", {"chapter_id": chapter_id})
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _update_planning_anchor(self, chapter_id: int) -> str:
        try:
            from planning_engine.rolling_integration import mark_anchor_changed
            mark_anchor_changed()
            return "success"
        except Exception as exc:
            return f"warning: {str(exc)}"

    def _chapter_path(self, chapter_id: int) -> Path:
        return self.context.root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"

    def _summary_path(self, chapter_id: int) -> Path:
        return self.context.root / "data" / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
