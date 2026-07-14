"""Version-aware, project-local repairs for Memory Health.

The service reuses the existing rule quality checker and local Chroma wrapper.
It never writes canon, prose, planning, or archived artefacts.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext
from system.data_store import DataStore
from system.quality_checker import build_quality_report, render_quality_report_markdown
from system.revision_service import RevisionService


ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryRepairService:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.store = DataStore(context)

    def quality_status(self, chapter_id: int | None = None) -> dict[str, Any]:
        chapters = [chapter_id] if chapter_id is not None else self._chapter_ids()
        if not chapters:
            return {
                "status": "not_applicable",
                "message": "\u5f53\u524d\u9879\u76ee\u5c1a\u65e0\u6709\u6548\u6b63\u53f2\u7ae0\u8282\uff0c\u65e0\u9700\u751f\u6210\u8d28\u91cf\u62a5\u544a\u3002",
                "repair_available": False,
                "items": [],
            }
        items = [self._quality_item(chapter) for chapter in chapters]
        states = {item["status"] for item in items}
        status = "available" if states == {"available"} else next(
            (value for value in ("generating", "failed", "stale", "missing") if value in states),
            "not_applicable",
        )
        return {
            "status": status,
            "message": self._quality_message(status),
            "repair_available": status in {"missing", "stale", "failed"},
            "items": items,
        }

    def build_quality_report(
        self, chapter_id: int, *, force: bool = False, analysis_profile: str = "lite"
    ) -> dict[str, Any]:
        item = self._quality_item(chapter_id)
        if item["status"] == "available" and not force:
            return {"status": "available", "report": item["report"], "created": False}
        canon = RevisionService(self.context).active_canon(chapter_id)
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        source = {
            "chapter_id": chapter_id,
            "manual_text": canon["content"],
            "generation": {"mode": "local_rule"},
        }
        report = build_quality_report(
            source,
            "canon",
            int(canon.get("version_number", 0) or 0),
            str(canon.get("content_path") or ""),
            plan,
            self._read("story_spec.json"),
            self._read("characters.json"),
            self._read("world_bible.json"),
            self._read("state.json"),
            use_llm=False,
        )
        report.update({
            "report_id": f"quality_{uuid4().hex}",
            "schema_version": "13.2",
            "project_id": self.context.root.name,
            "chapter_number": chapter_id,
            "canon_version_id": canon["canon_version_id"],
            "content_hash": canon["content_hash"],
            "analysis_profile": analysis_profile,
            "prompt_version": None,
            "status": "completed",
            "created_at": _now(),
        })
        directory = self.context.data_dir / "quality_reports" / "canon"
        directory.mkdir(parents=True, exist_ok=True)
        safe_version = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in canon["canon_version_id"])
        json_path = directory / f"chapter_{chapter_id:03d}_{safe_version}_quality.json"
        self.store.write_json(json_path, report, backup=True)
        self.store.write_markdown(json_path.with_suffix(".md"), render_quality_report_markdown(report))
        return {
            "status": "completed",
            "report": report,
            "created": True,
            "json_path": self.context.relative_path(json_path),
        }

    def vector_status(self) -> dict[str, Any]:
        metadata = self.store.read_json("data/vector_index/metadata.json", default={}, expected_type=dict) or {}
        sources = self._vector_snapshot()
        if not metadata:
            return self._vector_result("missing", sources=sources)
        if metadata.get("project_id") != self.context.root.name:
            return self._vector_result("failed", metadata, sources, "VECTOR_COLLECTION_PROJECT_MISMATCH")
        status = str(metadata.get("status") or "missing")
        if status in {"building", "failed", "not_configured", "degraded"}:
            return self._vector_result(status, metadata, sources)
        if not self._has_vector_sources(sources):
            return self._vector_result("empty", metadata, sources)
        if metadata.get("source_snapshot") != sources:
            return self._vector_result("stale", metadata, sources)
        return self._vector_result("ready", metadata, sources)

    def initialize_vector_index(self, *, rebuild: bool = False, job_id: str | None = None) -> dict[str, Any]:
        from system.vector_memory import build_or_update_index

        before = self.vector_status()
        metadata = dict(before.get("metadata") or {})
        metadata.update({
            "schema_version": "1.0",
            "project_id": self.context.root.name,
            "collection_name": metadata.get("collection_name") or f"storyos_{uuid4().hex[:16]}",
            "status": "building",
            "embedding_provider": "local_ngram",
            "embedding_model": "storyos-ngram-v1",
            "last_job_id": job_id,
            "last_error": None,
        })
        self._write_vector_metadata(metadata)
        result = build_or_update_index(self.context.data_dir)
        if result.get("status") == "failed":
            message = str(result.get("message") or "\u5411\u91cf\u7d22\u5f15\u6784\u5efa\u5931\u8d25\u3002")
            metadata.update({
                "status": "not_configured" if "chromadb" in message.lower() else "failed",
                "last_error": message,
            })
            self._write_vector_metadata(metadata)
            return {"status": metadata["status"], "message": message, "outputs": result.get("outputs", {})}
        snapshot = self._vector_snapshot()
        has_sources = self._has_vector_sources(snapshot)
        index_status = "ready" if has_sources and int((result.get("outputs") or {}).get("chunks_indexed", 0) or 0) > 0 else ("degraded" if has_sources else "empty")
        metadata.update({
            "status": index_status,
            "document_count": int((result.get("outputs") or {}).get("chunks_indexed", 0) or 0),
            "indexed_chapter_count": len(snapshot["current_canon_versions"]),
            "last_indexed_chapter": max(map(int, snapshot["current_canon_versions"].keys()), default=None),
            "last_indexed_at": _now(),
            "source_snapshot": snapshot,
            "last_error": None if index_status != "degraded" else "VECTOR_INDEX_EMPTY_WITH_SOURCES",
        })
        self._write_vector_metadata(metadata)
        return {
            "status": metadata["status"],
            "message": self._vector_message(metadata["status"]),
            "outputs": {**(result.get("outputs") or {}), "metadata_path": "data/vector_index/metadata.json", "incremental": not rebuild},
        }

    def _quality_item(self, chapter_id: int) -> dict[str, Any]:
        try:
            canon = RevisionService(self.context).active_canon(chapter_id)
        except Exception:
            return {"chapter_id": chapter_id, "status": "not_applicable", "message": "\u8be5\u7ae0\u8282\u6ca1\u6709\u6709\u6548\u6b63\u53f2\u7248\u672c\u3002"}
        active = self._active_repair_job("generate_quality_report", chapter_id, canon["canon_version_id"])
        if active:
            return {"chapter_id": chapter_id, "canon_version_id": canon["canon_version_id"], "status": "generating", "job_id": active["job_id"], "message": "\u6b63\u5728\u4e3a\u5f53\u524d\u6b63\u53f2\u7248\u672c\u751f\u6210\u672c\u5730\u8d28\u91cf\u62a5\u544a\u3002"}
        reports = self._reports_for(chapter_id)
        valid = next((report for report in reports if report.get("project_id") == self.context.root.name and report.get("canon_version_id") == canon["canon_version_id"] and report.get("content_hash") == canon["content_hash"] and report.get("status") == "completed"), None)
        if valid:
            return {"chapter_id": chapter_id, "canon_version_id": canon["canon_version_id"], "status": "available", "report": valid, "message": "\u5f53\u524d\u6b63\u53f2\u7248\u672c\u5df2\u6709\u6709\u6548\u8d28\u91cf\u62a5\u544a\u3002"}
        failed = next((report for report in reports if report.get("canon_version_id") == canon["canon_version_id"] and report.get("status") == "failed"), None)
        if failed:
            return {"chapter_id": chapter_id, "canon_version_id": canon["canon_version_id"], "status": "failed", "report": failed, "message": "\u6700\u8fd1\u4e00\u6b21\u8d28\u91cf\u62a5\u544a\u751f\u6210\u5931\u8d25\uff0c\u53ef\u5b89\u5168\u91cd\u8bd5\u3002"}
        legacy = next(iter(reports), None)
        return {"chapter_id": chapter_id, "canon_version_id": canon["canon_version_id"], "status": "stale" if legacy else "missing", "report": legacy, "message": "\u5386\u53f2\u8d28\u91cf\u62a5\u544a\u672a\u7ed1\u5b9a\u5f53\u524d\u6b63\u53f2\u7248\u672c\u3002" if legacy else "\u5f53\u524d\u6b63\u53f2\u7248\u672c\u7f3a\u5c11\u8d28\u91cf\u62a5\u544a\u3002"}

    def _reports_for(self, chapter_id: int) -> list[dict[str, Any]]:
        root = self.context.data_dir / "quality_reports"
        if not root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in root.rglob("*_quality.json"):
            row = self.store.read_json(path, default=None, expected_type=dict)
            if row and int(row.get("chapter_id", 0) or 0) == chapter_id:
                rows.append(row)
        return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)

    def _active_repair_job(self, job_type: str, chapter_id: int, version_id: str) -> dict[str, Any] | None:
        if not self.context.jobs_dir.exists():
            return None
        for path in self.context.jobs_dir.glob("job_*.json"):
            job = self.store.read_json(path, default={}, expected_type=dict) or {}
            params = job.get("parameters") or {}
            if job.get("job_type") == job_type and job.get("status") in ACTIVE_JOB_STATUSES and int(params.get("chapter_id", 0) or 0) == chapter_id and str(params.get("canon_version_id") or "") == version_id:
                return job
        return None

    def _chapter_ids(self) -> list[int]:
        if not self.context.chapters_dir.exists():
            return []
        result: list[int] = []
        for path in self.context.chapters_dir.glob("chapter_*.md"):
            try:
                result.append(int(path.stem.split("_")[-1]))
            except ValueError:
                continue
        return sorted(result)

    def _vector_snapshot(self) -> dict[str, Any]:
        canon: dict[str, Any] = {}
        for chapter in self._chapter_ids():
            try:
                active = RevisionService(self.context).active_canon(chapter)
                canon[str(chapter)] = {"canon_version_id": active["canon_version_id"], "content_hash": active["content_hash"]}
            except Exception:
                continue
        summaries: dict[str, str] = {}
        if self.context.summaries_dir.exists():
            for path in self.context.summaries_dir.glob("chapter_*_summary.json"):
                summaries[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        assets = {name: (self.context.data_dir / name).exists() for name in ("characters.json", "world_bible.json", "story_spec.json")}
        return {"current_canon_versions": canon, "summary_hashes": summaries, "project_assets": assets}

    def _vector_result(self, status: str, metadata: dict[str, Any] | None = None, sources: dict[str, Any] | None = None, error_code: str | None = None) -> dict[str, Any]:
        result = {"status": status, "message": self._vector_message(status), "repair_available": status in {"missing", "stale", "failed", "degraded", "not_configured"}, "metadata": metadata or {}, "source_snapshot": sources or {}}
        if error_code:
            result["error_code"] = error_code
        return result

    @staticmethod
    def _has_vector_sources(snapshot: dict[str, Any]) -> bool:
        return bool(snapshot.get("current_canon_versions") or snapshot.get("summary_hashes") or any(bool(value) for value in (snapshot.get("project_assets") or {}).values()))

    def _write_vector_metadata(self, metadata: dict[str, Any]) -> None:
        self.store.write_json("data/vector_index/metadata.json", metadata, backup=True)

    def _read(self, name: str) -> dict[str, Any]:
        return self.store.read_json(f"data/{name}", default={}, expected_type=dict) or {}

    @staticmethod
    def _quality_message(status: str) -> str:
        return {"available": "\u5f53\u524d\u6709\u6548\u6b63\u53f2\u5747\u6709\u8d28\u91cf\u62a5\u544a\u3002", "missing": "\u5f53\u524d\u6b63\u53f2\u7248\u672c\u7f3a\u5c11\u8d28\u91cf\u62a5\u544a\u3002", "stale": "\u73b0\u6709\u8d28\u91cf\u62a5\u544a\u5bf9\u5e94\u5386\u53f2\u6b63\u53f2\u7248\u672c\u3002", "generating": "\u8d28\u91cf\u62a5\u544a\u6b63\u5728\u751f\u6210\u3002", "failed": "\u8d28\u91cf\u62a5\u544a\u751f\u6210\u5931\u8d25\uff0c\u53ef\u91cd\u8bd5\u3002"}.get(status, "\u8d28\u91cf\u62a5\u544a\u72b6\u6001\u672a\u77e5\u3002")

    @staticmethod
    def _vector_message(status: str) -> str:
        return {"ready": "\u5411\u91cf\u7d22\u5f15\u5df2\u5c31\u7eea\u5e76\u4e0e\u5f53\u524d\u6709\u6548\u5185\u5bb9\u540c\u6b65\u3002", "empty": "\u7d22\u5f15\u5df2\u521d\u59cb\u5316\uff0c\u5f53\u524d\u6ca1\u6709\u53ef\u7d22\u5f15\u7684\u6709\u6548\u5185\u5bb9\u3002", "missing": "\u5411\u91cf\u7d22\u5f15\u5c1a\u672a\u521d\u59cb\u5316\u3002", "building": "\u5411\u91cf\u7d22\u5f15\u6b63\u5728\u6784\u5efa\u3002", "failed": "\u5411\u91cf\u7d22\u5f15\u6784\u5efa\u5931\u8d25\u3002", "stale": "\u5411\u91cf\u7d22\u5f15\u9700\u8981\u66f4\u65b0\u3002", "degraded": "\u5411\u91cf\u7d22\u5f15\u4e0d\u5b8c\u6574\u3002", "not_configured": "\u672c\u5730\u5411\u91cf\u7d22\u5f15\u4f9d\u8d56\u672a\u914d\u7f6e\uff0c\u4e0d\u5f71\u54cd\u57fa\u7840\u521b\u4f5c\u6d41\u7a0b\u3002"}.get(status, "\u5411\u91cf\u7d22\u5f15\u72b6\u6001\u672a\u77e5\u3002")
