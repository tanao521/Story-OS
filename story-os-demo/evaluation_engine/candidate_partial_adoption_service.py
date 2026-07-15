"""Stage 15.2B2 deterministic, author-selected partial candidate adoption."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext
from system.data_store import DataStore, DataWriteError
from system.text_diff import build_text_diff, split_text_for_diff
from .candidate_adoption_service import CandidateAdoptionError, CandidateAdoptionService, _hash, _now, _version_id
from .improvement_policy import ALLOWED_ACTIONS, ImprovementPolicyError
from .improvement_service import ImprovementService


class PartialAdoptionError(ImprovementPolicyError):
    pass


class CandidatePartialAdoptionService:
    """Applies a selected non-overlapping subset of already persisted patches.

    This service intentionally has no model dependency.  It never accepts patch
    text, anchors, ranges, or replacements from a client request.
    """

    PREVIEW_TTL = timedelta(minutes=30)
    ADOPTABLE = {"qualified", "review_required"}

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.store = DataStore(context)
        self.improvements = ImprovementService(context)
        self.adoptions = CandidateAdoptionService(context)

    def preview(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        request, candidate, source, current, candidate_text = self._validate_candidate(request_id)
        self._validate_preview_request(candidate, payload)
        selected = self._selected_patches(request, candidate, candidate_text, source, payload.get("selected_patch_ids"))
        result = self._apply(source, selected)
        result_hash = _hash(result)
        selected_ids = [item["patch_id"] for item in selected]
        all_patches = self._patches(request)
        unselected = [self._patch_summary(item) for item in all_patches if str(item.get("patch_id")) not in selected_ids]
        selected_summary = [self._patch_summary(item) for item in selected]
        resolved = sorted({str(issue) for item in selected for issue in item.get("issue_ids", []) if str(issue)})
        remaining = sorted({str(issue) for item in all_patches if str(item.get("patch_id")) not in selected_ids for issue in item.get("issue_ids", []) if str(issue)})
        preview = {
            "preview_id": f"partial_adoption_preview_{uuid4().hex}", "project_id": self.context.root.name,
            "request_id": request_id, "candidate_id": candidate["candidate_id"], "chapter_number": request["chapter_id"],
            "selected_patch_ids": selected_ids, "unselected_patch_ids": [item["patch_id"] for item in unselected],
            "selected_patches": selected_summary, "unselected_patches": unselected,
            "current_version_id": current["version_id"], "current_version_revision": current["revision"],
            "current_content_hash": current["content_hash"], "expected_source_version_id": _version_id(str(request["source_ref"]["source_type"]), int(request["source_ref"]["source_version"])),
            "expected_source_hash": request["source_hash"], "candidate_content_hash": candidate["content_hash"],
            "result_content_hash": result_hash, "candidate_status": request["state"],
            "changed_paragraphs": sorted({int(item["paragraph_start"]) for item in selected}),
            "change_statistics": build_text_diff(source, result).get("summary", {}), "result_diff": build_text_diff(source, result),
            "result_content": result, "resolved_issue_ids": resolved, "remaining_issue_ids": remaining,
            "warnings": self._warnings(request), "state": "preview", "created_at": _now(),
            "expires_at": (datetime.now(timezone.utc) + self.PREVIEW_TTL).isoformat(),
        }
        self.store.write_json(self._preview_path(request_id, preview["preview_id"]), preview)
        return preview

    def adopt(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        operation_id = str(payload.get("operation_id") or "").strip()
        if not operation_id:
            raise PartialAdoptionError("PARTIAL_ADOPTION_OPERATION_REQUIRED", "operation_id is required for partial adoption.")
        request = self.improvements.get(request_id)
        if request.get("project_id") != self.context.root.name:
            raise PartialAdoptionError("PARTIAL_ADOPTION_PROJECT_MISMATCH", "Candidate belongs to a different project.")
        if request.get("state") == "partially_adopted":
            if request.get("partial_adoption_operation_id") == operation_id:
                return {"request": self.improvements.public(request), "new_version": request.get("partially_adopted_version"), "warnings": request.get("partial_adoption_warnings", [])}, True
            raise PartialAdoptionError("PARTIAL_ADOPTION_ALREADY_COMPLETED", "Only one partial adoption is allowed for a candidate.")
        lock = self.adoptions._lock_for(int(request["chapter_id"]))
        if not lock.acquire(blocking=False):
            raise PartialAdoptionError("DRAFT_VERSION_LOCK_CONFLICT", "A work-version operation is already active for this chapter.")
        try:
            preview = self._preview(request_id, str(payload.get("preview_id") or ""))
            request, candidate, source, current, candidate_text = self._validate_candidate(request_id)
            self._validate_payload(request, candidate, current, preview, payload)
            selected = self._selected_patches(request, candidate, candidate_text, source, preview.get("selected_patch_ids"))
            result = self._apply(source, selected)
            if _hash(result) != str(preview.get("result_content_hash") or ""):
                raise PartialAdoptionError("PARTIAL_ADOPTION_RESULT_HASH_MISMATCH", "The deterministic merge result no longer matches the preview.")
            snapshot = {"snapshot_id": f"partial_adoption_snapshot_{uuid4().hex}", "created_at": _now(), "current": current, "selected_index": self.adoptions._index_payload(int(request["chapter_id"]))}
            self.store.write_json(f"data/evaluations/improvements/{request_id}/partial_adoption_snapshots/{snapshot['snapshot_id']}.json", snapshot)
            provenance = {
                "source_type": "quality_improvement_partial", "source_candidate_id": candidate["candidate_id"],
                "source_improvement_request_id": request["improvement_id"], "source_evaluation_id": request["evaluation_id"],
                "candidate_evaluation_id": candidate["candidate_id"], "comparison_id": request["improvement_id"],
                "selected_patch_ids": preview["selected_patch_ids"], "unselected_patch_ids": preview["unselected_patch_ids"],
                "partial_adoption_preview_id": preview["preview_id"], "partial_adoption_operation_id": operation_id,
                "parent_version_id": current["version_id"], "author_confirm": bool(payload.get("author_confirm")),
                "review_reason": str(payload.get("review_reason") or ""),
            }
            new_version = self.adoptions._create_work_version(request, candidate, source, result, payload, current, provenance_kind="quality_improvement_partial", provenance=provenance)
            original_request = deepcopy(request)
            original_report = deepcopy(self.improvements._evaluation(str(request["evaluation_id"])))
            request.update({"state": "partially_adopted", "partially_adopted_version_id": new_version["version_id"],
                            "partially_adopted_version": new_version, "partially_adopted_at": _now(),
                            "partial_adoption_operation_id": operation_id, "partial_adoption_preview_id": preview["preview_id"],
                            "partial_adoption": {"selected_patch_ids": preview["selected_patch_ids"], "unselected_patch_ids": preview["unselected_patch_ids"],
                                                 "result_content_hash": preview["result_content_hash"], "diff_preview_id": preview["preview_id"]},
                            "author_confirmation": {"author_confirm": bool(payload.get("author_confirm")), "review_reason": str(payload.get("review_reason") or "")}, "updated_at": _now()})
            try:
                self._mark_baseline_stale(request)
                self.improvements._save(request)
            except Exception:
                self.adoptions._rollback_work_version(request, new_version, snapshot["selected_index"])
                try: self.adoptions._restore_baseline_report(original_report, request)
                except DataWriteError: pass
                request.clear(); request.update(original_request)
                raise
            warnings: list[str] = []
            try: self.adoptions._audit("candidate_partially_adopted", request, new_version, operation_id)
            except DataWriteError as exc: warnings.append(f"audit_pending: {str(exc)[:160]}")
            if warnings:
                request["partial_adoption_warnings"] = warnings
                try: self.improvements._save(request)
                except DataWriteError: pass
            return {"request": self.improvements.public(request), "new_version": new_version, "warnings": warnings}, False
        finally:
            lock.release()

    def _validate_candidate(self, request_id: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], str]:
        request = self.improvements.get(request_id)
        if request.get("project_id") != self.context.root.name:
            raise PartialAdoptionError("PARTIAL_ADOPTION_PROJECT_MISMATCH", "Candidate belongs to a different project.")
        if request.get("state") not in self.ADOPTABLE:
            if request.get("state") == "partially_adopted": raise PartialAdoptionError("PARTIAL_ADOPTION_ALREADY_COMPLETED", "Only one partial adoption is allowed for a candidate.")
            raise PartialAdoptionError("PARTIAL_ADOPTION_CANDIDATE_NOT_READY", "Candidate is not eligible for partial adoption.")
        try:
            checked, candidate, source_ref, current, candidate_text = self.adoptions._validate_candidate(request_id, preview=True)
        except CandidateAdoptionError as exc:
            code = "PARTIAL_ADOPTION_CANDIDATE_NOT_READY" if exc.code == "CANDIDATE_ADOPTION_PREVIEW_STALE" else "PARTIAL_ADOPTION_SOURCE_CHANGED"
            raise PartialAdoptionError(code, str(exc)) from exc
        if not isinstance(candidate.get("diff"), dict):
            raise PartialAdoptionError("PARTIAL_ADOPTION_CANDIDATE_NOT_READY", "Candidate diff is unavailable.")
        source, _ = self.improvements._source(self.improvements._evaluation(str(request["evaluation_id"])))
        if _hash(source) != str(request.get("source_hash") or ""):
            raise PartialAdoptionError("PARTIAL_ADOPTION_SOURCE_CHANGED", "Original candidate source text has changed.")
        return checked, candidate, source, current, candidate_text

    def _patches(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        plan = request.get("plan") if isinstance(request.get("plan"), dict) else {}
        patches = plan.get("patches") if isinstance(plan.get("patches"), list) else []
        return [item for item in patches if isinstance(item, dict)]

    def _selected_patches(self, request: dict[str, Any], candidate: dict[str, Any], candidate_text: str, source: str, selected_ids: Any) -> list[dict[str, Any]]:
        if not isinstance(selected_ids, list) or not selected_ids:
            raise PartialAdoptionError("PARTIAL_ADOPTION_NO_PATCH_SELECTED", "Select at least one persisted patch.")
        ids = [str(item).strip() for item in selected_ids]
        if any(not item for item in ids) or len(set(ids)) != len(ids):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_CONFLICT", "Patch ids must be unique.")
        patches = self._patches(request); by_id = {str(item.get("patch_id") or ""): item for item in patches}
        selected: list[dict[str, Any]] = []
        for patch_id in sorted(ids):
            patch = by_id.get(patch_id)
            if not patch: raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_FOUND", f"Patch was not found: {patch_id}")
            self._validate_patch(patch, source, candidate_text, candidate.get("diff") or {})
            selected.append(patch)
        selected_ids_set = set(ids)
        for patch in selected:
            dependencies = {str(item) for item in patch.get("depends_on_patch_ids", []) if str(item)}
            if not dependencies.issubset(selected_ids_set):
                raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_DEPENDENCY_MISSING", "Selected patch dependencies are missing.")
            conflicts = {str(item) for item in patch.get("conflicts_with_patch_ids", []) if str(item)}
            if conflicts & selected_ids_set:
                raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_CONFLICT", "Selected patches have a persisted conflict.")
        self._validate_overlaps(selected)
        return selected

    def _validate_patch(self, patch: dict[str, Any], source: str, candidate_text: str, candidate_diff: dict[str, Any]) -> None:
        anchor, replacement = str(patch.get("original_anchor") or patch.get("anchor") or ""), str(patch.get("replacement_text") or "")
        try: start, end = int(patch.get("paragraph_start")), int(patch.get("paragraph_end"))
        except (TypeError, ValueError): raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE", "Patch paragraph range is invalid.")
        if (str(patch.get("risk") or "") != "low" or str(patch.get("action") or "") not in ALLOWED_ACTIONS or not anchor or not replacement or start < 1 or end < start):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE", "Patch is not an eligible low-risk deterministic replacement.")
        if source.count(anchor) != 1 or candidate_text.count(replacement) != 1:
            raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE", "Patch anchors are unavailable or ambiguous in source/candidate text.")
        paragraphs = split_text_for_diff(source)
        if end > len(paragraphs) or anchor not in "\n\n".join(paragraphs[start - 1:end]):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE", "Patch range does not match its source anchor.")
        lines = candidate_diff.get("diff_lines") if isinstance(candidate_diff.get("diff_lines"), list) else []
        removed = any(str(line.get("type")) == "removed" and anchor in str(line.get("text") or "") for line in lines if isinstance(line, dict))
        added = any(str(line.get("type")) == "added" and replacement in str(line.get("text") or "") for line in lines if isinstance(line, dict))
        if not (removed and added):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE", "Patch is not represented by the persisted candidate diff.")

    def _validate_overlaps(self, patches: list[dict[str, Any]]) -> None:
        for index, left in enumerate(patches):
            left_anchor = str(left.get("original_anchor") or left.get("anchor"))
            for right in patches[index + 1:]:
                right_anchor = str(right.get("original_anchor") or right.get("anchor"))
                ranges_overlap = int(left["paragraph_start"]) <= int(right["paragraph_end"]) and int(right["paragraph_start"]) <= int(left["paragraph_end"])
                anchors_overlap = left_anchor in right_anchor or right_anchor in left_anchor
                if ranges_overlap or anchors_overlap:
                    raise PartialAdoptionError("PARTIAL_ADOPTION_PATCH_OVERLAP", "Selected patches overlap and cannot be merged deterministically.")

    def _apply(self, source: str, patches: list[dict[str, Any]]) -> str:
        value = source
        for patch in sorted(patches, key=lambda item: (-int(item["paragraph_start"]), str(item["patch_id"]))):
            anchor, replacement = str(patch.get("original_anchor") or patch.get("anchor")), str(patch["replacement_text"])
            if value.count(anchor) != 1:
                raise PartialAdoptionError("PARTIAL_ADOPTION_SOURCE_CHANGED", "Patch source anchor changed before merge.")
            value = value.replace(anchor, replacement, 1)
        return value

    def _validate_payload(self, request: dict[str, Any], candidate: dict[str, Any], current: dict[str, Any], preview: dict[str, Any], payload: dict[str, Any]) -> None:
        if len(str(payload.get("operation_id") or "")) > 128 or len(str(payload.get("review_reason") or "")) > 2000:
            raise PartialAdoptionError("PARTIAL_ADOPTION_INPUT_INVALID", "operation_id or review_reason exceeds the allowed length.")
        if request.get("state") == "review_required" and (not bool(payload.get("author_confirm")) or not str(payload.get("review_reason") or "").strip()):
            raise PartialAdoptionError("PARTIAL_ADOPTION_REVIEW_REASON_REQUIRED", "review_required candidates need author confirmation and a reason.")
        expected = {"candidate_id": candidate["candidate_id"], "expected_current_version_id": current["version_id"], "expected_current_version_revision": current["revision"], "expected_current_content_hash": current["content_hash"], "expected_candidate_hash": candidate["content_hash"], "expected_result_content_hash": preview.get("result_content_hash")}
        preview_values = {"candidate_id": preview.get("candidate_id"), "expected_current_version_id": preview.get("current_version_id"), "expected_current_version_revision": preview.get("current_version_revision"), "expected_current_content_hash": preview.get("current_content_hash"), "expected_candidate_hash": preview.get("candidate_content_hash"), "expected_result_content_hash": preview.get("result_content_hash")}
        for key, actual in expected.items():
            if str(payload.get(key)) != str(actual) or str(preview_values[key]) != str(actual):
                code = "PARTIAL_ADOPTION_RESULT_HASH_MISMATCH" if key == "expected_result_content_hash" else "DRAFT_VERSION_REVISION_CONFLICT" if key == "expected_current_version_revision" else "PARTIAL_ADOPTION_PREVIEW_STALE"
                raise PartialAdoptionError(code, "Preview, candidate, or current work version changed.")
        submitted_ids = payload.get("selected_patch_ids")
        if submitted_ids is not None and (not isinstance(submitted_ids, list) or sorted({str(item).strip() for item in submitted_ids}) != list(preview.get("selected_patch_ids") or [])):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PREVIEW_STALE", "Client patch selection does not match the preview.")

    def _validate_preview_request(self, candidate: dict[str, Any], payload: dict[str, Any]) -> None:
        selected = payload.get("selected_patch_ids")
        if selected is not None and (not isinstance(selected, list) or len(selected) > 25):
            raise PartialAdoptionError("PARTIAL_ADOPTION_SELECTION_INVALID", "selected_patch_ids must be a list of at most 25 items.")
        if payload.get("candidate_id") not in (None, "", candidate.get("candidate_id")):
            raise PartialAdoptionError("PARTIAL_ADOPTION_PREVIEW_STALE", "Candidate does not match the partial-adoption preview request.")

    def _preview(self, request_id: str, preview_id: str) -> dict[str, Any]:
        preview = self.store.read_json(self._preview_path(request_id, preview_id), default=None, expected_type=dict)
        if not preview or preview.get("project_id") != self.context.root.name or preview.get("request_id") != request_id:
            raise PartialAdoptionError("PARTIAL_ADOPTION_PREVIEW_NOT_FOUND", "Partial-adoption preview was not found for this project.")
        try: expired = datetime.fromisoformat(str(preview["expires_at"])) <= datetime.now(timezone.utc)
        except (KeyError, ValueError): expired = True
        if expired: raise PartialAdoptionError("PARTIAL_ADOPTION_PREVIEW_STALE", "Partial-adoption preview expired; create a new preview.")
        return preview

    def _mark_baseline_stale(self, request: dict[str, Any]) -> None:
        report = self.improvements._evaluation(str(request["evaluation_id"])); report["status_override"] = "stale"; report["stale_reason"] = "candidate_partially_adopted_as_new_work_version"; report["partially_adopted_candidate_evaluation_id"] = (request.get("candidate") or {}).get("candidate_id")
        chapter = int((report.get("target_ref") or {}).get("chapter_number") or request["chapter_id"])
        self.store.write_json(f"data/evaluations/chapter_{chapter:03d}/{report['evaluation_id']}.json", report)

    def _patch_summary(self, patch: dict[str, Any]) -> dict[str, Any]:
        return {key: patch.get(key) for key in ("patch_id", "issue_ids", "paragraph_start", "paragraph_end", "anchor", "action", "risk", "depends_on_patch_ids", "conflicts_with_patch_ids")}

    def _warnings(self, request: dict[str, Any]) -> list[str]:
        warnings = ["部分采用仅创建新的工作正文版本；不会覆盖来源版本或提交正史。"]
        if request.get("state") == "review_required": warnings.append("该候选需要作者确认并填写复核原因。")
        return warnings

    def _preview_path(self, request_id: str, preview_id: str) -> str:
        return f"data/evaluations/improvements/{request_id}/partial_previews/{preview_id}.json"
