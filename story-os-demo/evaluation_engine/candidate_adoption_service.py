"""Stage 15.2B1 adoption of an immutable evaluation candidate into a work version.

This deliberately uses the existing draft/edited/manual version format.  It never
uses RevisionService because that service activates canon and invalidates derived
story data, which is outside this stage's authority.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext
from system.data_store import DataStore, DataWriteError
from system.manual_editor import render_manual_markdown
from system.version_manager import build_versioned_paths, get_next_version_number, list_versions, read_version_payload
from .improvement_policy import ImprovementPolicyError
from .improvement_service import ImprovementService


_LOCKS: dict[tuple[str, int], threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _hash(value: str) -> str: return sha256(value.encode("utf-8")).hexdigest()
def _version_id(source_type: str, version: int) -> str: return f"{source_type}_v{version:03d}"


class CandidateAdoptionError(ImprovementPolicyError):
    pass


class CandidateAdoptionService:
    PREVIEW_TTL = timedelta(minutes=30)
    ADOPTABLE = {"qualified", "review_required"}
    DISCARDABLE = {"qualified", "review_required", "rejected", "failed", "cancelled"}

    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store, self.improvements = context, DataStore(context), ImprovementService(context)

    def preview(self, request_id: str) -> dict[str, Any]:
        request, candidate, source, current, text = self._validate_candidate(request_id, preview=True)
        preview = {
            "preview_id": f"adoption_preview_{uuid4().hex}", "project_id": self.context.root.name,
            "request_id": request_id, "candidate_id": candidate["candidate_id"], "chapter_number": request["chapter_id"],
            "current_version_id": current["version_id"], "current_version_revision": current["revision"],
            "current_content_hash": current["content_hash"], "expected_source_version_id": _version_id(source["source_type"], source["source_version"]),
            "expected_source_hash": request["source_hash"], "candidate_content_hash": candidate["content_hash"],
            "candidate_status": request["state"], "comparison_recommendation": (request.get("comparison") or {}).get("recommendation"),
            "gate_before": (request.get("comparison") or {}).get("gate_before"), "gate_after": (request.get("comparison") or {}).get("gate_after"),
            "overall_score_before": (request.get("comparison") or {}).get("baseline_score"), "overall_score_after": (request.get("comparison") or {}).get("candidate_score"),
            "change_statistics": (candidate.get("diff") or {}).get("summary", {}), "warnings": self._preview_warnings(request),
            "created_at": _now(), "expires_at": (datetime.now(timezone.utc) + self.PREVIEW_TTL).isoformat(),
        }
        self.store.write_json(self._preview_path(request_id, preview["preview_id"]), preview)
        return preview

    def adopt(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        operation_id = str(payload.get("operation_id") or "").strip()
        if not operation_id:
            raise CandidateAdoptionError("ADOPTION_OPERATION_REQUIRED", "operation_id is required for adoption.")
        request = self.improvements.get(request_id)
        if request.get("project_id") != self.context.root.name:
            raise CandidateAdoptionError("CANDIDATE_PROJECT_MISMATCH", "Candidate belongs to a different project.")
        if request.get("state") == "adopted":
            if request.get("adoption_operation_id") == operation_id:
                return {"request": self.improvements.public(request), "new_version": request.get("adopted_version"), "warnings": request.get("adoption_warnings", [])}, True
            raise CandidateAdoptionError("CANDIDATE_ALREADY_ADOPTED", "Candidate was already adopted.")
        if request.get("state") == "partially_adopted":
            raise CandidateAdoptionError("CANDIDATE_ALREADY_PARTIALLY_ADOPTED", "A partially adopted candidate cannot be adopted as a whole.")
        lock = self._lock_for(int(request["chapter_id"]))
        if not lock.acquire(blocking=False):
            raise CandidateAdoptionError("DRAFT_VERSION_LOCK_CONFLICT", "A work-version operation is already active for this chapter.")
        try:
            preview = self._preview(request_id, str(payload.get("preview_id") or ""))
            self._validate_adoption_payload(request, preview, payload)
            request, candidate, source, current, text = self._validate_candidate(request_id, preview=True)
            self._validate_preview_matches(preview, request, candidate, current, payload)
            snapshot = {"snapshot_id": f"adoption_snapshot_{uuid4().hex}", "created_at": _now(), "current": current, "selected_index": self._index_payload(request["chapter_id"])}
            self.store.write_json(f"data/evaluations/improvements/{request_id}/adoption_snapshots/{snapshot['snapshot_id']}.json", snapshot)
            new_version = self._create_work_version(request, candidate, source, text, payload, current)
            original_request, original_report = deepcopy(request), deepcopy(self.improvements._evaluation(str(request["evaluation_id"])))
            request.update({"state": "adopted", "adopted_version_id": new_version["version_id"], "adopted_version": new_version,
                            "adopted_at": _now(), "adoption_operation_id": operation_id, "adoption_preview_id": preview["preview_id"],
                            "adopted_candidate_evaluation_id": candidate["candidate_id"], "author_confirmation": {"author_confirm": bool(payload.get("author_confirm")), "review_reason": str(payload.get("review_reason") or "")}, "updated_at": _now()})
            try:
                self._mark_baseline_stale(request)
                self.improvements._save(request)
            except Exception:
                self._rollback_work_version(request, new_version, snapshot["selected_index"])
                try: self._restore_baseline_report(original_report, request)
                except DataWriteError: pass
                request.clear(); request.update(original_request)
                raise
            warnings: list[str] = []
            try: self._audit("candidate_adopted", request, new_version, operation_id)
            except DataWriteError as exc: warnings.append(f"audit_pending: {str(exc)[:160]}")
            if warnings:
                request["adoption_warnings"] = warnings
                try: self.improvements._save(request)
                except DataWriteError: pass
            return {"request": self.improvements.public(request), "new_version": new_version, "warnings": warnings}, False
        finally:
            lock.release()

    def discard(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        request = self.improvements.get(request_id); candidate = request.get("candidate") or {}
        operation_id = str(payload.get("operation_id") or "").strip()
        if not operation_id: raise CandidateAdoptionError("DISCARD_OPERATION_REQUIRED", "operation_id is required for discard.")
        if request.get("state") == "discarded":
            if request.get("discard_operation_id") == operation_id: return self.improvements.public(request), True
            raise CandidateAdoptionError("CANDIDATE_ALREADY_DISCARDED", "Candidate was already discarded.")
        if request.get("state") == "adopted": raise CandidateAdoptionError("CANDIDATE_ALREADY_ADOPTED", "An adopted candidate cannot be discarded.")
        if request.get("state") == "partially_adopted": raise CandidateAdoptionError("CANDIDATE_ALREADY_PARTIALLY_ADOPTED", "A partially adopted candidate is immutable.")
        if request.get("state") not in self.DISCARDABLE: raise CandidateAdoptionError("CANDIDATE_STATE_INVALID", "Candidate cannot be discarded in its current state.")
        if str(payload.get("candidate_id") or "") != str(candidate.get("candidate_id") or "") or str(payload.get("expected_candidate_hash") or "") != str(candidate.get("content_hash") or ""):
            raise CandidateAdoptionError("CANDIDATE_ADOPTION_PREVIEW_STALE", "Candidate identity or hash changed.")
        self._candidate_text(candidate)
        request.update({"state": "discarded", "discarded_at": _now(), "discard_reason": str(payload.get("reason") or "").strip(), "discard_operation_id": operation_id, "updated_at": _now()})
        self.improvements._save(request)
        try: self._audit("candidate_discarded", request, None, operation_id)
        except DataWriteError: pass
        return self.improvements.public(request), False

    def _validate_candidate(self, request_id: str, *, preview: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        request = self.improvements.get(request_id); candidate = request.get("candidate") or {}
        if request.get("project_id") != self.context.root.name: raise CandidateAdoptionError("CANDIDATE_PROJECT_MISMATCH", "Candidate belongs to a different project.")
        if preview and request.get("state") not in self.ADOPTABLE:
            code = "CANDIDATE_REJECTED" if request.get("state") == "rejected" else "CANDIDATE_STATE_INVALID"
            raise CandidateAdoptionError(code, "Candidate is not eligible for adoption preview.")
        if not isinstance(request.get("evaluation"), dict) or not isinstance(request.get("comparison"), dict):
            raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "Candidate evaluation or comparison is unavailable.")
        if request.get("comparison", {}).get("recommendation") != request.get("state"):
            raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "Candidate state no longer matches its comparison recommendation.")
        text = self._candidate_text(candidate)
        source = dict(request.get("source_ref") or {})
        if not source or int(source.get("chapter_number") or 0) != int(request.get("chapter_id") or 0): raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "Candidate source metadata is invalid.")
        current = self._current_version(int(request["chapter_id"]))
        if current["version_id"] != _version_id(str(source.get("source_type")), int(source.get("source_version") or 0)) or current["content_hash"] != str(request.get("source_hash") or ""):
            raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "The current work version no longer matches the candidate source.")
        if not self.improvements._evaluation(str(request.get("evaluation_id") or "")): raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "Source evaluation no longer exists.")
        return request, candidate, source, current, text

    def _candidate_text(self, candidate: dict[str, Any]) -> str:
        path = str(candidate.get("content_path") or ""); text = self.store.read_markdown(path, default=None)
        if text is None or _hash(text) != str(candidate.get("content_hash") or ""):
            raise CandidateAdoptionError("CANDIDATE_ADOPTION_PREVIEW_STALE", "Candidate content is missing or its hash changed.")
        return text

    def _current_version(self, chapter: int) -> dict[str, Any]:
        versions = list_versions(chapter, self.context.data_dir); selected = versions.get("selected") if isinstance(versions.get("selected"), dict) else {}
        info = None
        if selected: info = next((row for key in ("manual", "edited", "drafts") for row in versions.get(key, []) if str(row.get("source_type")) == str(selected.get("source_type")) and int(row.get("version", 0)) == int(selected.get("version", 0))), None)
        info = info or next((rows[-1] for rows in (versions.get("manual", []), versions.get("edited", []), versions.get("drafts", [])) if rows), None)
        if not info: raise CandidateAdoptionError("CANDIDATE_SOURCE_CHANGED", "No current work version exists.")
        payload = read_version_payload(info); text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
        index = self._index_payload(chapter)
        return {"source_type": info["source_type"], "version": int(info["version"]), "version_id": _version_id(str(info["source_type"]), int(info["version"])), "content_hash": _hash(text), "revision": int(index.get("selection_revision", 1) or 1), "info": info}

    def _create_work_version(self, request: dict[str, Any], candidate: dict[str, Any], source: dict[str, Any], text: str, payload: dict[str, Any], current: dict[str, Any], *, provenance_kind: str = "quality_improvement", provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        chapter = int(request["chapter_id"]); version = get_next_version_number(chapter, "manual", self.context.data_dir); paths = build_versioned_paths(chapter, "manual", version, self.context.data_dir)
        base_payload = read_version_payload(current["info"]); now = _now(); version_id = _version_id("manual", version)
        details = {"source_candidate_id": candidate["candidate_id"], "source_improvement_request_id": request["improvement_id"], "source_evaluation_id": request["evaluation_id"], "candidate_evaluation_id": candidate["candidate_id"], "comparison_id": request["improvement_id"], "adoption_operation_id": str(payload["operation_id"]), "author_confirm": bool(payload.get("author_confirm")), "review_reason": str(payload.get("review_reason") or "")}
        if provenance: details.update(provenance)
        manual = {"manual_version": "2.3", "chapter_id": chapter, "chapter_title": str(base_payload.get("chapter_title") or ""), "status": "manual", "version": version, "version_label": version_id, "source_type": current["source_type"], "source_version": current["version"], "source_path": current["info"].get("json_path", ""), "manual_text": text, "actual_word_count": len(text.strip()), "created_at": now, "updated_at": now, "editing": {"mode": provenance_kind, "model": "none", "fallback_used": False, "warnings": []}, "checks": {"valid_text": True, "warnings": []}, provenance_kind: details}
        json_path, markdown_path = str(paths["json_path"]), str(paths["markdown_path"]); old_index = self._index_payload(chapter)
        written: list[str] = []
        try:
            self.store.write_json(json_path, manual); written.append(json_path)
            self.store.write_markdown(markdown_path, render_manual_markdown(manual)); written.append(markdown_path)
            index = list_versions(chapter, self.context.data_dir); index["selected"] = {"source_type": "manual", "version": version, "version_label": version_id, "json_path": json_path, "markdown_path": markdown_path, "selected_at": now}; index["selection_revision"] = int(old_index.get("selection_revision", 1) or 1) + 1
            self.store.write_json(f"data/versions/chapter_{chapter:03d}_versions.json", index)
        except Exception:
            for path in reversed(written):
                try: self.store.path(path).unlink(missing_ok=True)
                except OSError: pass
            try: self.store.write_json(f"data/versions/chapter_{chapter:03d}_versions.json", old_index)
            except DataWriteError: pass
            raise
        return {"version_id": version_id, "source_type": "manual", "version": version, "version_label": version_id, "json_path": json_path, "markdown_path": markdown_path, "parent_version_id": current["version_id"], "content_hash": _hash(text), "revision": int(old_index.get("selection_revision", 1) or 1) + 1}

    def _preview(self, request_id: str, preview_id: str) -> dict[str, Any]:
        preview = self.store.read_json(self._preview_path(request_id, preview_id), default=None, expected_type=dict)
        if not preview or preview.get("project_id") != self.context.root.name: raise CandidateAdoptionError("CANDIDATE_ADOPTION_PREVIEW_STALE", "Adoption preview was not found for this project.")
        try: expired = datetime.fromisoformat(str(preview["expires_at"])) <= datetime.now(timezone.utc)
        except (KeyError, ValueError): expired = True
        if expired: raise CandidateAdoptionError("CANDIDATE_ADOPTION_PREVIEW_STALE", "Adoption preview expired; create a new preview.")
        return preview

    def _validate_adoption_payload(self, request: dict[str, Any], preview: dict[str, Any], payload: dict[str, Any]) -> None:
        if len(str(payload.get("operation_id") or "")) > 128 or len(str(payload.get("review_reason") or "")) > 2000:
            raise CandidateAdoptionError("CANDIDATE_ADOPTION_INPUT_INVALID", "operation_id or review_reason exceeds the allowed length.")
        if str(payload.get("candidate_id") or "") != str(preview.get("candidate_id") or ""): raise CandidateAdoptionError("CANDIDATE_ADOPTION_PREVIEW_STALE", "Candidate does not match the preview.")
        if request.get("state") == "review_required" and (not bool(payload.get("author_confirm")) or not str(payload.get("review_reason") or "").strip()):
            raise CandidateAdoptionError("AUTHOR_REVIEW_REQUIRED", "review_required candidates need author_confirm and review_reason.")

    def _validate_preview_matches(self, preview: dict[str, Any], request: dict[str, Any], candidate: dict[str, Any], current: dict[str, Any], payload: dict[str, Any]) -> None:
        expected = {"expected_current_version_id": current["version_id"], "expected_current_version_revision": current["revision"], "expected_current_content_hash": current["content_hash"], "expected_candidate_hash": candidate["content_hash"]}
        preview_keys = {"expected_current_version_id": "current_version_id", "expected_current_version_revision": "current_version_revision", "expected_current_content_hash": "current_content_hash", "expected_candidate_hash": "candidate_content_hash"}
        for key, actual in expected.items():
            if str(payload.get(key)) != str(actual) or str(preview.get(preview_keys[key])) != str(actual):
                code = "DRAFT_VERSION_REVISION_CONFLICT" if key == "expected_current_version_revision" else "CANDIDATE_ADOPTION_PREVIEW_STALE"
                raise CandidateAdoptionError(code, "Preview, current version, or candidate hash changed.")

    def _mark_baseline_stale(self, request: dict[str, Any]) -> None:
        report = self.improvements._evaluation(str(request["evaluation_id"])); report["status_override"] = "stale"; report["stale_reason"] = "candidate_adopted_as_new_work_version"; report["adopted_candidate_evaluation_id"] = (request.get("candidate") or {}).get("candidate_id")
        ref = report.get("target_ref") or {}; chapter = int(ref.get("chapter_number") or request["chapter_id"])
        self.store.write_json(f"data/evaluations/chapter_{chapter:03d}/{report['evaluation_id']}.json", report)

    def _restore_baseline_report(self, report: dict[str, Any], request: dict[str, Any]) -> None:
        ref = report.get("target_ref") or {}; chapter = int(ref.get("chapter_number") or request["chapter_id"])
        self.store.write_json(f"data/evaluations/chapter_{chapter:03d}/{report['evaluation_id']}.json", report)

    def _rollback_work_version(self, request: dict[str, Any], version: dict[str, Any], old_index: dict[str, Any]) -> None:
        chapter = int(request["chapter_id"])
        try: self.store.write_json(f"data/versions/chapter_{chapter:03d}_versions.json", old_index)
        except DataWriteError: pass
        for key in ("json_path", "markdown_path"):
            try: self.store.path(str(version.get(key) or "")).unlink(missing_ok=True)
            except OSError: pass

    def _preview_warnings(self, request: dict[str, Any]) -> list[str]:
        comparison = request.get("comparison") or {}; warnings = []
        if request.get("state") == "review_required": warnings.append("该候选存在需作者复核的风险；确认采用时必须勾选确认并填写原因。")
        if comparison.get("major_regression"): warnings.append("比较记录包含主要退化风险。")
        return warnings

    def _index_payload(self, chapter: int) -> dict[str, Any]: return self.store.read_json(f"data/versions/chapter_{chapter:03d}_versions.json", default={"version_index": "1.5", "chapter_id": chapter}, expected_type=dict) or {"version_index": "1.5", "chapter_id": chapter}
    def _preview_path(self, request_id: str, preview_id: str) -> str: return f"data/evaluations/improvements/{request_id}/previews/{preview_id}.json"
    def _lock_for(self, chapter: int) -> threading.RLock:
        with _LOCK_GUARD: return _LOCKS.setdefault((str(self.context.root.resolve()), chapter), threading.RLock())
    def _audit(self, action: str, request: dict[str, Any], version: dict[str, Any] | None, operation_id: str) -> None:
        path = "data/audit/improvement_adoption_audit.json"; rows = self.store.read_json(path, default=[], expected_type=list) or []
        rows.append({"audit_id": f"adoption_audit_{uuid4().hex}", "project_id": self.context.root.name, "action": action, "request_id": request["improvement_id"], "candidate_id": (request.get("candidate") or {}).get("candidate_id"), "chapter_id": request["chapter_id"], "version_id": (version or {}).get("version_id"), "operation_id": operation_id, "created_at": _now()}); self.store.write_json(path, rows[-500:])
