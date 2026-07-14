"""Append-only canon revision, restore, and archive recovery services.

The service deliberately owns only revision data.  It never re-resolves the
active project: callers provide a ProjectContext captured at request/job time.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore, DataWriteError


class RevisionError(RuntimeError):
    code = "REVISION_ERROR"


class RevisionNotFoundError(RevisionError):
    code = "REVISION_NOT_FOUND"


class CandidateNotFoundError(RevisionError):
    code = "CANDIDATE_NOT_FOUND"


class RevisionStateError(RevisionError):
    code = "REVISION_NOT_READY"


class RevisionStaleError(RevisionError):
    code = "REVISION_STALE"


class CanonVersionNotFoundError(RevisionError):
    code = "CANON_VERSION_NOT_FOUND"


class ChapterOperationConflict(RevisionError):
    code = "CHAPTER_OPERATION_CONFLICT"


_LOCKS: dict[tuple[str, int], threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _word_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text))


def _chapter_path(chapter_id: int) -> str:
    return f"data/chapters/chapter_{chapter_id:03d}.md"


def _canon_index_path(chapter_id: int) -> str:
    return f"data/canon_versions/chapter_{chapter_id:03d}/index.json"


def _canon_file_path(chapter_id: int, number: int) -> str:
    return f"data/canon_versions/chapter_{chapter_id:03d}/canon_v{number:03d}.md"


class RevisionService:
    """Project-scoped, append-only revision data and canon activation logic."""

    def __init__(self, context: ProjectContext):
        self.context = context
        self.store = DataStore(context)

    # --- Canon versions -------------------------------------------------
    def list_canon_versions(self, chapter_id: int) -> list[dict[str, Any]]:
        return list(self._canon_index(chapter_id)["versions"])

    def get_canon_version(self, chapter_id: int, version_id: str) -> dict[str, Any]:
        version = next((item for item in self._canon_index(chapter_id)["versions"] if item["canon_version_id"] == version_id), None)
        if not version:
            raise CanonVersionNotFoundError("Canon version does not exist for this chapter.")
        item = dict(version)
        item["content"] = self.store.read_markdown(item["content_path"], strict=True) or ""
        return item

    def active_canon(self, chapter_id: int) -> dict[str, Any]:
        index = self._canon_index(chapter_id)
        version = next((item for item in index["versions"] if item.get("active")), None)
        if not version:
            raise CanonVersionNotFoundError("This chapter has no active canon version.")
        result = dict(version)
        result["content"] = self.store.read_markdown(result["content_path"], strict=True) or ""
        return result

    def _canon_index(self, chapter_id: int) -> dict[str, Any]:
        path = _canon_index_path(chapter_id)
        index = self.store.read_json(path, default=None, expected_type=dict)
        if isinstance(index, dict) and isinstance(index.get("versions"), list):
            return index
        chapter = _chapter_path(chapter_id)
        text = self.store.read_markdown(chapter, default=None)
        if text is None:
            raise CanonVersionNotFoundError("Committed chapter file does not exist.")
        # Gentle legacy adoption: copy to the version area, never move or edit the old chapter.
        version_id = f"legacy-chapter-{chapter_id:03d}"
        record = self._canon_record(chapter_id, 1, version_id, _canon_file_path(chapter_id, 1), text, "legacy")
        record["active"] = True
        record["activated_at"] = _now()
        self.store.write_markdown(record["content_path"], text)
        index = {"schema_version": "1.0", "chapter_id": chapter_id, "current_version_id": version_id, "versions": [record]}
        self.store.write_json(path, index)
        self._audit("legacy_canon_indexed", "canon_version", version_id, chapter_id, "success", "Legacy chapter indexed as canon v001.")
        return index

    @staticmethod
    def _canon_record(chapter_id: int, number: int, version_id: str, content_path: str, content: str, source: str, **extra: Any) -> dict[str, Any]:
        return {"canon_version_id": version_id, "chapter_id": chapter_id, "version_number": number,
                "content_path": content_path, "content_hash": _hash(content), "created_at": _now(),
                "activated_at": None, "deactivated_at": None, "active": False, "source": source,
                "revision_id": extra.get("revision_id", ""), "replaces_version_id": extra.get("replaces_version_id", ""),
                "restored_from_version_id": extra.get("restored_from_version_id", ""), "review_id": extra.get("review_id", ""),
                "word_count": _word_count(content)}

    # --- Revisions and candidates --------------------------------------
    def create_revision(self, chapter_id: int, *, reason: str = "", scope: str = "", source_version_id: str | None = None) -> dict[str, Any]:
        base = self.get_canon_version(chapter_id, source_version_id) if source_version_id else self.active_canon(chapter_id)
        revision_id = _id("revision")
        candidate = self._save_candidate(revision_id, chapter_id, base["content"], source="manual", notes="Revision baseline", ordinal=1)
        revision = {"schema_version": "1.0", "revision_id": revision_id, "project_id": self.context.root.name,
                    "chapter_id": chapter_id, "chapter_number": chapter_id, "status": "editing",
                    "base_canon_version_id": base["canon_version_id"], "base_canon_hash": base["content_hash"],
                    "base_chapter_file_hash": _hash(self.store.read_markdown(_chapter_path(chapter_id), strict=True) or ""),
                    "base_updated_at": base.get("activated_at") or base.get("created_at"), "candidate_version_ids": [candidate["candidate_version_id"]],
                    "active_candidate_version_id": candidate["candidate_version_id"], "created_at": _now(), "updated_at": _now(),
                    "created_by": "user", "reason": reason[:500], "scope": scope[:500], "review_status": "pending",
                    "reviews": [], "quality_report_id": None, "continuity_report_id": None, "impact_report_id": None,
                    "approved_candidate_version_id": None, "completed_at": None, "cancelled_at": None, "warnings": []}
        self._save_revision(revision)
        self._audit("revision_created", "revision", revision_id, chapter_id, "success", "Revision created from fixed canon baseline.")
        return revision

    def list_revisions(self, chapter_id: int | None = None) -> list[dict[str, Any]]:
        root = self.store.path("data/revisions")
        if not root.exists(): return []
        records = []
        for path in root.glob("revision_*/revision.json"):
            item = self.store.read_json(path, default=None, expected_type=dict)
            if item and (chapter_id is None or int(item.get("chapter_id", 0)) == chapter_id): records.append(item)
        return sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        item = self.store.read_json(f"data/revisions/{revision_id}/revision.json", default=None, expected_type=dict)
        if not item: raise RevisionNotFoundError("Revision does not exist in this project.")
        return item

    def list_candidates(self, revision_id: str) -> list[dict[str, Any]]:
        revision = self.get_revision(revision_id)
        return [self.get_candidate(revision_id, item) for item in revision.get("candidate_version_ids", [])]

    def get_candidate(self, revision_id: str, candidate_id: str) -> dict[str, Any]:
        item = self.store.read_json(f"data/revisions/{revision_id}/candidates/{candidate_id}.json", default=None, expected_type=dict)
        if not item: raise CandidateNotFoundError("Revision candidate does not exist.")
        result = dict(item); result["content"] = self.store.read_markdown(result["content_path"], strict=True) or ""
        return result

    def save_candidate(self, revision_id: str, content: str, *, source: str = "manual", notes: str = "") -> dict[str, Any]:
        revision = self.get_revision(revision_id)
        if revision["status"] in {"completed", "cancelled", "stale", "applying"}: raise RevisionStateError("This revision can no longer accept candidates.")
        candidate = self._save_candidate(revision_id, int(revision["chapter_id"]), content, source=source, notes=notes, ordinal=len(revision["candidate_version_ids"]) + 1)
        revision["candidate_version_ids"].append(candidate["candidate_version_id"]); revision["active_candidate_version_id"] = candidate["candidate_version_id"]
        revision["status"] = "ready_for_check"; revision["review_status"] = "pending"; revision["updated_at"] = _now(); self._save_revision(revision)
        self._audit("candidate_saved", "revision_candidate", candidate["candidate_version_id"], int(revision["chapter_id"]), "success", "New immutable revision candidate saved.")
        return candidate

    def _save_candidate(self, revision_id: str, chapter_id: int, content: str, *, source: str, notes: str, ordinal: int) -> dict[str, Any]:
        candidate_id = f"candidate_{ordinal:03d}_{uuid.uuid4().hex[:10]}"; path = f"data/revisions/{revision_id}/candidates/{candidate_id}.md"
        item = {"candidate_version_id": candidate_id, "revision_id": revision_id, "chapter_id": chapter_id, "source": source,
                "created_at": _now(), "updated_at": _now(), "content_path": path, "content_hash": _hash(content),
                "word_count": _word_count(content), "summary": content.replace("\n", " ")[:160], "notes": notes[:500],
                "quality_status": "not_checked", "continuity_status": "not_checked"}
        self.store.write_markdown(path, content); self.store.write_json(f"data/revisions/{revision_id}/candidates/{candidate_id}.json", item)
        return item

    def cancel(self, revision_id: str) -> dict[str, Any]:
        revision = self.get_revision(revision_id)
        if revision["status"] in {"completed", "applying"}: raise RevisionStateError("Completed or applying revisions cannot be cancelled.")
        revision.update({"status": "cancelled", "cancelled_at": _now(), "updated_at": _now()}); self._save_revision(revision)
        self._audit("revision_cancelled", "revision", revision_id, int(revision["chapter_id"]), "success", "Revision cancelled; candidates are retained.")
        return revision

    # --- Analysis and review -------------------------------------------
    def diff(self, revision_id: str, left_candidate_id: str | None = None, right_candidate_id: str | None = None) -> dict[str, Any]:
        revision = self.get_revision(revision_id); base = self.active_canon(int(revision["chapter_id"]))
        left = self.get_candidate(revision_id, left_candidate_id) if left_candidate_id else base
        right = self.get_candidate(revision_id, right_candidate_id or revision["active_candidate_version_id"])
        lines = list(difflib.unified_diff(left["content"].splitlines(), right["content"].splitlines(), fromfile=left.get("candidate_version_id", base["canon_version_id"]), tofile=right["candidate_version_id"], lineterm=""))
        return {"left_id": left.get("candidate_version_id", base["canon_version_id"]), "right_id": right["candidate_version_id"], "unified_diff": lines,
                "word_count": {"before": _word_count(left["content"]), "after": _word_count(right["content"]), "change": _word_count(right["content"]) - _word_count(left["content"])},
                "paragraph_change": len([x for x in lines if x.startswith("+") and not x.startswith("+++")]) - len([x for x in lines if x.startswith("-") and not x.startswith("---")]),
                "entity_changes": self._entity_changes(left["content"], right["content"])}

    def _entity_changes(self, before: str, after: str) -> dict[str, list[str]]:
        terms = lambda value: set(re.findall(r"[\u4e00-\u9fff]{2,6}", value))
        old, new = terms(before), terms(after)
        return {"added": sorted(new - old)[:30], "removed": sorted(old - new)[:30]}

    def quality_check(self, revision_id: str, candidate_id: str | None = None) -> dict[str, Any]:
        from system.quality_checker import build_quality_report
        revision = self.get_revision(revision_id); candidate = self.get_candidate(revision_id, candidate_id or revision["active_candidate_version_id"])
        chapter = int(revision["chapter_id"]); data = lambda name: self.store.read_json(f"data/{name}.json", default={}, expected_type=dict) or {}
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {"chapter_id": chapter}
        report = build_quality_report({"chapter_id": chapter, "manual_text": candidate["content"]}, "revision_candidate", 1, candidate["content_path"], plan, data("story_spec"), data("characters"), data("world_bible"), data("state"), use_llm=False)
        report.update({"revision_id": revision_id, "candidate_version_id": candidate["candidate_version_id"], "base_canon_version_id": revision["base_canon_version_id"]})
        report_id = _id("revision_quality"); self.store.write_json(f"data/revisions/{revision_id}/reports/{report_id}.json", report)
        revision.update({"quality_report_id": report_id, "status": "waiting_for_review", "updated_at": _now()}); self._save_revision(revision)
        self._audit("revision_quality_checked", "revision", revision_id, chapter, "success", "Local revision quality report saved.")
        return {"report_id": report_id, "report": report}

    def continuity_check(self, revision_id: str, candidate_id: str | None = None) -> dict[str, Any]:
        from system.continuity_checker import check_chapter_continuity
        revision = self.get_revision(revision_id); chapter = int(revision["chapter_id"]); candidate = self.get_candidate(revision_id, candidate_id or revision["active_candidate_version_id"])
        previous = self.store.read_markdown(_chapter_path(chapter - 1), default="") if chapter > 1 else ""
        following = self.store.read_markdown(_chapter_path(chapter + 1), default="") or ""
        report = check_chapter_continuity(previous, candidate["content"]) if previous else {"verdict": "pass", "score": 1.0, "issues": [], "suggestions": [], "mode": "not_applicable"}
        removed = self._entity_changes(self.active_canon(chapter)["content"], candidate["content"])["removed"]
        references = [term for term in removed if term and term in following]
        report.update({"revision_id": revision_id, "candidate_version_id": candidate["candidate_version_id"], "chapter_id": chapter, "following_reference_risks": references[:20], "existing_issues": [], "new_issues": report.get("issues", []), "resolved_issues": []})
        report_id = _id("revision_continuity"); self.store.write_json(f"data/revisions/{revision_id}/reports/{report_id}.json", report)
        revision.update({"continuity_report_id": report_id, "status": "waiting_for_review", "updated_at": _now()}); self._save_revision(revision)
        self._audit("revision_continuity_checked", "revision", revision_id, chapter, "success", "Revision continuity report saved.")
        return {"report_id": report_id, "report": report}

    def impact_analysis(self, revision_id: str, candidate_id: str | None = None) -> dict[str, Any]:
        revision = self.get_revision(revision_id); chapter = int(revision["chapter_id"]); candidate = self.get_candidate(revision_id, candidate_id or revision["active_candidate_version_id"])
        removed = self._entity_changes(self.active_canon(chapter)["content"], candidate["content"])["removed"]; impacts: list[dict[str, Any]] = []
        for path in sorted(self.store.path("data/chapters").glob("chapter_*.md")):
            match = re.search(r"chapter_(\d+)\.md$", path.name)
            if not match or int(match.group(1)) <= chapter: continue
            text = self.store.read_markdown(path, default="") or ""; hits = [term for term in removed if term in text]
            if hits: impacts.append({"severity": "blocking" if len(hits) >= 2 else "high", "entity_type": "committed_chapter", "entity_id": path.stem, "reason": f"Following chapter still references removed terms: {', '.join(hits[:4])}.", "suggestion": "Confirm the change or revise the affected following chapter."})
        report = {"revision_id": revision_id, "candidate_version_id": candidate["candidate_version_id"], "chapter_id": chapter, "impacts": impacts, "blocking": any(x["severity"] == "blocking" for x in impacts), "mode": "local_rule"}
        report_id = _id("revision_impact"); self.store.write_json(f"data/revisions/{revision_id}/reports/{report_id}.json", report)
        revision.update({"impact_report_id": report_id, "status": "waiting_for_review", "updated_at": _now()}); self._save_revision(revision)
        self._audit("revision_impact_analyzed", "revision", revision_id, chapter, "success", "Revision impact analysis saved.")
        return {"report_id": report_id, "report": report}

    def review(self, revision_id: str, decision: str, *, candidate_id: str | None = None, comment: str = "", confirmed_risks: bool = False) -> dict[str, Any]:
        if decision not in {"approve", "request_changes", "reject"}: raise RevisionStateError("Invalid review decision.")
        revision = self.get_revision(revision_id); candidate_id = candidate_id or revision["active_candidate_version_id"]
        self.get_candidate(revision_id, candidate_id)
        if decision == "approve":
            impact = self._load_report(revision, "impact_report_id")
            if impact.get("blocking") and not confirmed_risks: raise RevisionStateError("REVISION_BLOCKED_BY_IMPACT")
            revision.update({"status": "approved", "review_status": "approved", "approved_candidate_version_id": candidate_id})
        elif decision == "request_changes": revision.update({"status": "editing", "review_status": "changes_requested"})
        else: revision.update({"status": "editing", "review_status": "rejected"})
        review = {"review_id": _id("revision_review"), "revision_id": revision_id, "candidate_version_id": candidate_id, "decision": decision, "reviewer": "user", "comment": comment[:1000], "confirmed_risks": confirmed_risks, "created_at": _now()}
        revision.setdefault("reviews", []).append(review); revision["updated_at"] = _now(); self._save_revision(revision)
        self._audit(f"revision_{decision}", "revision", revision_id, int(revision["chapter_id"]), "success", "Human revision review recorded.")
        return {"revision": revision, "review": review}

    def _load_report(self, revision: dict[str, Any], field: str) -> dict[str, Any]:
        value = revision.get(field)
        return self.store.read_json(f"data/revisions/{revision['revision_id']}/reports/{value}.json", default={}, expected_type=dict) if value else {}

    # --- Canon activation / restore ------------------------------------
    def apply(self, revision_id: str) -> dict[str, Any]:
        revision = self.get_revision(revision_id)
        if revision.get("status") != "approved": raise RevisionStateError("A revision must be approved by a human before it can be applied.")
        chapter = int(revision["chapter_id"]); lock = self._lock_for(chapter)
        if not lock.acquire(blocking=False): raise ChapterOperationConflict("A conflicting operation is already running for this chapter.")
        try:
            revision["status"] = "applying"; revision["updated_at"] = _now(); self._save_revision(revision)
            active = self.active_canon(chapter)
            current_chapter_hash = _hash(self.store.read_markdown(_chapter_path(chapter), strict=True) or "")
            if active["canon_version_id"] != revision["base_canon_version_id"] or active["content_hash"] != revision["base_canon_hash"] or current_chapter_hash != revision["base_chapter_file_hash"]:
                revision.update({"status": "stale", "updated_at": _now()}); self._save_revision(revision); raise RevisionStaleError("Current canon changed since this revision was created.")
            candidate = self.get_candidate(revision_id, revision["approved_candidate_version_id"])
            if _hash(candidate["content"]) != candidate["content_hash"]: raise RevisionStateError("Candidate content hash no longer matches its record.")
            index = self._canon_index(chapter); number = max((int(item["version_number"]) for item in index["versions"]), default=0) + 1
            version_id = f"canon-chapter-{chapter:03d}-v{number:03d}"; content_path = _canon_file_path(chapter, number)
            new = self._canon_record(chapter, number, version_id, content_path, candidate["content"], "revision", revision_id=revision_id, replaces_version_id=active["canon_version_id"], review_id=(revision.get("reviews") or [{}])[-1].get("review_id", "")); new["active"] = True; new["activated_at"] = _now()
            original = self.store.read_markdown(_chapter_path(chapter), strict=True) or ""
            try:
                self.store.write_markdown(content_path, candidate["content"])
                self.store.write_markdown(_chapter_path(chapter), candidate["content"], backup=True)
                for item in index["versions"]:
                    if item.get("active"): item["active"] = False; item["deactivated_at"] = _now()
                index["versions"].append(new); index["current_version_id"] = version_id; self.store.write_json(_canon_index_path(chapter), index, backup=True)
            except Exception:
                # Restore the old chapter if activation could not be completed; old canon snapshot remains intact.
                try: self.store.write_markdown(_chapter_path(chapter), original, backup=False)
                except DataWriteError: pass
                revision.update({"status": "failed", "updated_at": _now()}); self._save_revision(revision); raise
            self._mark_derived_stale(chapter, active["canon_version_id"], version_id)
            try:
                from system.narrative_memory_service import NarrativeMemoryService
                NarrativeMemoryService(self.context).invalidate_from(chapter)
            except Exception as exc:
                revision.setdefault("warnings", []).append(f"Narrative memory rebuild required: {str(exc)[:160]}")
            revision.update({"status": "completed", "completed_at": _now(), "updated_at": _now()}); self._save_revision(revision)
            self._audit("revision_applied", "revision", revision_id, chapter, "success", f"Activated {version_id}; prior canon retained.")
            warnings = ["Summary, vector memory, and planning-derived artifacts are marked stale and need rebuilding."]
            reflection_job = None
            try:
                from system.job_manager import get_job_manager
                reflection_job = get_job_manager().create_job("chapter_reflection", {"chapter_id": chapter, "created_by": "system"}, context=self.context)
            except Exception as exc:
                warnings.append(f"Creative reflection can be retried manually: {str(exc)[:160]}")
            try:
                from planning_engine.rolling_integration import mark_anchor_changed
                rolling_notice = mark_anchor_changed(self.context, "canon_revision_applied")
                if rolling_notice.get("warning") and rolling_notice.get("changed"):
                    warnings.append(str(rolling_notice["warning"]))
            except Exception as exc:
                warnings.append(f"Rolling window status check can be retried manually: {str(exc)[:160]}")
            return {"chapter_id": chapter, "canon_version": new, "revision": revision, "creative_reflection_job": reflection_job, "warnings": warnings}
        finally: lock.release()

    def restore_canon(self, chapter_id: int, version_id: str, *, confirmed_risks: bool = False) -> dict[str, Any]:
        target = self.get_canon_version(chapter_id, version_id)
        # The revision baseline must remain the current canon; only its candidate carries historical content.
        revision = self.create_revision(chapter_id, reason=f"Restore {version_id}", scope="historical_canon_restore")
        candidate = self.save_candidate(revision["revision_id"], target["content"], source="restored_version", notes=f"Restored from {version_id}")
        self.review(revision["revision_id"], "approve", candidate_id=candidate["candidate_version_id"], confirmed_risks=confirmed_risks, comment="Historical canon restore approved by user.")
        result = self.apply(revision["revision_id"])
        result["canon_version"]["restored_from_version_id"] = version_id
        # Persist provenance in the canonical index as well.
        index = self._canon_index(chapter_id)
        index["versions"][-1]["restored_from_version_id"] = version_id
        self.store.write_json(_canon_index_path(chapter_id), index)
        self._audit("canon_restored", "canon_version", version_id, chapter_id, "success", "Historical canon content restored as a new append-only version.")
        return result

    def _mark_derived_stale(self, chapter: int, old_version: str, new_version: str) -> None:
        path = "data/derived_state.json"; state = self.store.read_json(path, default={"schema_version": "1.0", "artifacts": []}, expected_type=dict) or {"schema_version": "1.0", "artifacts": []}
        kinds = ["chapter_summary", "vector_memory", "context_cache", "character_state", "foreshadow_state", "timeline_state", "quality_report", "continuity_report", "obsidian_export"]
        artifacts = [item for item in state.get("artifacts", []) if not (item.get("chapter_id") == chapter and item.get("artifact_type") in kinds)]
        artifacts.extend({"artifact_type": kind, "chapter_id": chapter, "source_canon_version_id": old_version, "current_canon_version_id": new_version, "status": "stale", "updated_at": _now()} for kind in kinds)
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        if int(plan.get("chapter_id", 0) or 0) == chapter + 1:
            artifacts.append({"artifact_type": "next_chapter_plan", "chapter_id": chapter + 1, "source_canon_version_id": old_version, "current_canon_version_id": new_version, "status": "stale", "updated_at": _now()})
        state["artifacts"] = artifacts; self.store.write_json(path, state)

    # --- Archive centre -------------------------------------------------
    def list_archive(self, item_type: str | None = None) -> list[dict[str, Any]]:
        root = self.context.archive_dir
        if not root.exists(): return []
        entries = []
        for meta in root.rglob("archive_meta.json"):
            data = self.store.read_json(meta, default=None, expected_type=dict)
            if not data: continue
            kind = str(data.get("item_type") or data.get("source_type") or "chapter")
            if item_type and kind != item_type: continue
            entries.append({"archive_id": str(data.get("archive_id") or _hash(meta.as_posix())[:20]), "item_type": kind, "chapter_id": data.get("chapter_id"), "archived_at": data.get("archived_at") or data.get("created_at"), "reason": data.get("reason", ""), "restorable": True, "metadata": data, "archive_meta_path": self.context.relative_path(meta)})
        return sorted(entries, key=lambda item: str(item.get("archived_at", "")), reverse=True)

    def get_archive(self, archive_id: str) -> dict[str, Any]:
        entry = next((item for item in self.list_archive() if item["archive_id"] == archive_id), None)
        if not entry: raise RevisionNotFoundError("ARCHIVE_ITEM_NOT_FOUND")
        return entry

    def restore_archive(self, archive_id: str) -> dict[str, Any]:
        entry = self.get_archive(archive_id)
        meta = dict(entry.get("metadata") or {})
        # A committed chapter is never copied back over current canon through archive recovery.
        if str(entry.get("item_type")) == "chapter":
            raise RevisionStateError("ARCHIVE_ITEM_NOT_RESTORABLE: restore a historical canon version through the canon restore workflow.")
        meta_path = self.store.path(entry["archive_meta_path"])
        archive_root = meta_path.parent
        restored: list[str] = []
        for file_info in meta.get("files", []):
            if not isinstance(file_info, dict): continue
            archived_relative = str(file_info.get("archived_path", "")); source_relative = str(file_info.get("source", ""))
            source = archive_root / archived_relative
            if not source.exists() or not source.is_file():
                raise RevisionStateError("ARCHIVE_ITEM_NOT_RESTORABLE: archived file is missing.")
            # Recover source material into a dedicated non-active recovery area. Never overwrite a live draft/version.
            target = self.store.path(f"data/restored_archive/{archive_id}/{source_relative}")
            self.store.write_text(target, source.read_text(encoding="utf-8"))
            restored.append(self.context.relative_path(target))
        restore_id = _id("restore")
        record = {"restore_id": restore_id, "archive_id": archive_id, "project_id": self.context.root.name, "restored_at": _now(), "strategy": "restore_as_new_recovery_copy", "files": restored}
        self.store.write_json(f"data/archive/restore_records/{restore_id}.json", record)
        self._audit("archive_restored", "archive", archive_id, int(entry.get("chapter_id") or 0), "success", "Archived source material restored as non-overwriting recovery copies.")
        return record

    def _save_revision(self, revision: dict[str, Any]) -> None:
        revision["updated_at"] = _now(); self.store.write_json(f"data/revisions/{revision['revision_id']}/revision.json", revision)

    def _audit(self, action_type: str, entity_type: str, entity_id: str, chapter_id: int, result: str, summary: str) -> None:
        path = "data/audit/revision_audit.json"; records = self.store.read_json(path, default=[], expected_type=list) or []
        records.append({"action_id": _id("audit"), "project_id": self.context.root.name, "action_type": action_type, "entity_type": entity_type, "entity_id": entity_id, "chapter_id": chapter_id, "timestamp": _now(), "result": result, "summary": summary[:500], "related_job_id": ""})
        self.store.write_json(path, records[-500:])

    def _lock_for(self, chapter_id: int) -> threading.RLock:
        key = (str(self.context.root.resolve()), chapter_id)
        with _LOCKS_GUARD: return _LOCKS.setdefault(key, threading.RLock())
