"""Stage 15.2A: create bounded candidate revisions without changing canon."""
from __future__ import annotations

from datetime import datetime, timezone
import difflib
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.project_context import ProjectContext
from system.data_store import DataStore
from system.text_diff import build_text_diff, split_text_for_diff
from system.version_manager import list_versions, read_version_payload
from .candidate_evaluator import evaluate_candidate
from .improvement_policy import ImprovementPolicyError, budget, selectable_issues, validate_actions
from .improvement_prompt import plan_prompt, revision_prompt


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _hash(value: str) -> str: return sha256(value.encode("utf-8")).hexdigest()


class ImprovementService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def prepare(self, evaluation_id: str, payload: dict[str, Any], active_jobs: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], bool]:
        report = self._evaluation(evaluation_id)
        if report.get("project_id") != self.context.root.name or report.get("target_type") != "chapter_draft":
            raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "Evaluation does not belong to this project draft.")
        source, source_ref = self._source(report)
        if _hash(source) != str(report.get("source_snapshots", {}).get("chapter_content_hash", "")):
            raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "The evaluated source text has changed.")
        selectable, disabled = selectable_issues(report)
        allowed = {str(item["issue_id"]) for item in selectable}
        chosen = [str(item) for item in payload.get("issue_ids", []) if str(item)] or list(allowed)
        if not chosen or any(item not in allowed for item in chosen):
            raise ImprovementPolicyError("IMPROVEMENT_ISSUE_NOT_AUTO_FIXABLE", "Only selected auto_low_risk issues may be revised.")
        chapter = int(report.get("target_ref", {}).get("chapter_number") or 0)
        if any(job.get("job_type") == "quality_improvement" and int((job.get("parameters") or {}).get("chapter_id", -1)) == chapter for job in active_jobs or []):
            raise ImprovementPolicyError("CHAPTER_OPERATION_CONFLICT", "A quality refresh is already active for this chapter.")
        operation_id = str(payload.get("operation_id", "")).strip()
        if operation_id:
            prior = self._find_operation(operation_id)
            if prior:
                if prior.get("source_hash") != _hash(source):
                    raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "This operation id belongs to a different source.")
                return prior, True
        count = sum(1 for item in self._index().get("improvements", []) if item.get("evaluation_id") == evaluation_id and item.get("source_hash") == _hash(source))
        if count >= 3:
            raise ImprovementPolicyError("IMPROVEMENT_CANDIDATE_LIMIT", "At most three candidates may be generated for one evaluated source.")
        limits = budget(str(payload.get("budget", "standard")))
        request_id = f"improvement_{uuid4().hex}"
        request = {"improvement_id": request_id, "project_id": self.context.root.name, "chapter_id": chapter,
                   "evaluation_id": evaluation_id, "source_hash": _hash(source), "source_ref": source_ref,
                   "issue_ids": chosen, "policy_id": "chapter-low-risk-v1", "mode": "restricted_candidate",
                   "operation_id": operation_id, "created_by": "user", "created_at": _now(), "updated_at": _now(),
                   "state": "planning", "budget": limits, "disabled_issues": disabled, "plan": None, "candidate": None,
                   "evaluation": None, "comparison": None}
        self._save(request)
        return request, False

    def run(self, improvement_id: str, *, job_id: str = "", emit: Callable[[dict[str, Any]], None] | None = None, cancelled: Callable[[], bool] | None = None, gateway: Any = None, route_snapshots: dict[str, Any] | None = None) -> dict[str, Any]:
        request = self.get(improvement_id)
        check = lambda: bool(cancelled and cancelled())
        def step(name: str, status: str, **extra: Any) -> None:
            if emit: emit({"name": name, "label": name.replace("-", " "), "status": status, **extra})
        if check(): return self._cancel(request)
        source, _ = self._source(self._evaluation(request["evaluation_id"]))
        if _hash(source) != request["source_hash"]: raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "Source changed while the job was queued.")
        issues, _ = selectable_issues(self._evaluation(request["evaluation_id"]))
        chosen = [item for item in issues if item["issue_id"] in request["issue_ids"]]
        from llm.model_gateway import get_model_gateway
        gateway = gateway or get_model_gateway(self.context)
        step("improvement-plan", "running")
        routes = route_snapshots or {}
        planned = gateway.generate_json("chapter_quality_plan", plan_prompt(source, chosen, request["budget"]), prompt_id="chapter_quality_plan_v1", job_id=job_id, chapter_id=request["chapter_id"], cancellation_requested=cancelled, route_snapshot=routes.get("chapter_quality_plan"))
        patches = planned.get("patches") if isinstance(planned.get("patches"), list) else []
        validate_actions(patches, request["budget"])
        request.update({"state": "generating", "plan": {"patches": patches, "issue_ids": request["issue_ids"]}, "updated_at": _now()}); self._save(request); step("improvement-plan", "completed", outputs={"patch_count": len(patches)})
        if check(): return self._cancel(request)
        step("improvement-candidate", "running")
        generated = gateway.generate_json("chapter_quality_revision", revision_prompt(source, request["plan"], request["budget"]), prompt_id="chapter_quality_revision_v1", job_id=job_id, chapter_id=request["chapter_id"], cancellation_requested=cancelled, route_snapshot=routes.get("chapter_quality_revision"))
        text, persisted_patches = self._apply_replacements(source, request["plan"]["patches"], generated.get("replacements"))
        # The candidate is still generated exactly once by the bounded phase-A
        # workflow.  Persist the verified replacement mapping with the plan so a
        # later author-directed partial adoption never has to infer or regenerate
        # a patch from candidate text.
        request["plan"]["patches"] = persisted_patches
        diff = build_text_diff(source, text)
        self._validate_budget(source, text, diff, request["budget"])
        if check(): return self._cancel(request)
        candidate = self._save_candidate(request, text, diff)
        request.update({"state": "evaluating", "candidate": candidate, "updated_at": _now()}); self._save(request); step("improvement-candidate", "completed", outputs={"candidate_id": candidate["candidate_id"]})
        step("improvement-evaluate", "running")
        candidate_eval = evaluate_candidate(self.context, request["chapter_id"], text, self._evaluation(request["evaluation_id"]).get("profile_id", "chapter-default-v1"))
        request["evaluation"] = candidate_eval; request["state"] = "evaluating"; self._save(request); step("improvement-evaluate", "completed")
        step("improvement-compare", "running")
        request["comparison"] = self._compare(self._evaluation(request["evaluation_id"]), candidate_eval, diff)
        request["state"] = request["comparison"]["recommendation"]; request["updated_at"] = _now(); self._save(request); step("improvement-compare", "completed", outputs={"recommendation": request["state"]})
        return self.public(request)

    def get(self, improvement_id: str) -> dict[str, Any]:
        item = self.store.read_json(f"data/evaluations/improvements/{improvement_id}/request.json", default=None, expected_type=dict)
        if not item: raise ImprovementPolicyError("IMPROVEMENT_NOT_FOUND", "Improvement request was not found.")
        return item

    def public(self, item: dict[str, Any]) -> dict[str, Any]:
        value = dict(item); candidate = value.get("candidate")
        if isinstance(candidate, dict): value["candidate"] = {key: val for key, val in candidate.items() if key != "content_path"}
        return value

    def _evaluation(self, evaluation_id: str) -> dict[str, Any]:
        index = self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict) or {}
        row = next((item for item in index.get("reports", []) if isinstance(item, dict) and item.get("evaluation_id") == evaluation_id), None)
        report = self.store.read_json(str(row.get("path", "")), default=None, expected_type=dict) if row else None
        if not report: raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "Evaluation report no longer exists.")
        return report

    def _source(self, report: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        ref = report.get("target_ref", {}) if isinstance(report.get("target_ref"), dict) else {}
        chapter, source_type, version = int(ref.get("chapter_number") or 0), str(ref.get("source_type") or ""), int(ref.get("source_version") or 0)
        versions = list_versions(chapter, self.context.data_dir); collection = {"draft": "drafts", "edited": "edited", "manual": "manual"}.get(source_type)
        row = next((item for item in versions.get(collection, []) if int(item.get("version", 0) or 0) == version), None) if collection else None
        if not row: raise ImprovementPolicyError("IMPROVEMENT_SOURCE_CHANGED", "The evaluated chapter version is unavailable.")
        payload = read_version_payload(row); text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
        return text, {"chapter_number": chapter, "source_type": source_type, "source_version": version}

    def _apply_replacements(self, source: str, patches: list[dict[str, Any]], replacements: Any) -> tuple[str, list[dict[str, Any]]]:
        if not isinstance(replacements, list) or len(replacements) != len(patches):
            raise ImprovementPolicyError("IMPROVEMENT_CANDIDATE_INVALID", "Model must return one local replacement per planned patch.")
        value, persisted = source, []
        for index, patch in enumerate(patches):
            row = replacements[index] if isinstance(replacements[index], dict) else {}
            anchor, replacement = str(row.get("anchor", "")), str(row.get("replacement", ""))
            if anchor != str(patch["anchor"]) or not replacement.strip() or len(replacement) > max(len(anchor) * 3 + 120, 300):
                raise ImprovementPolicyError("IMPROVEMENT_CANDIDATE_INVALID", "Candidate replacement is not a bounded local edit.")
            if value.count(anchor) != 1: raise ImprovementPolicyError("IMPROVEMENT_CANDIDATE_INVALID", "Candidate anchor is missing or ambiguous.")
            value = value.replace(anchor, replacement, 1)
            stable = sha256(f"{index}|{patch.get('anchor', '')}|{patch.get('action', '')}|{','.join(map(str, patch.get('issue_ids', [])))}".encode("utf-8")).hexdigest()[:12]
            persisted.append({**patch, "patch_id": str(patch.get("patch_id") or f"patch_{index + 1:03d}_{stable}"),
                              "original_anchor": anchor, "replacement_text": replacement,
                              "risk": "low", "depends_on_patch_ids": list(patch.get("depends_on_patch_ids") or []),
                              "conflicts_with_patch_ids": list(patch.get("conflicts_with_patch_ids") or [])})
        return value, persisted

    def _validate_budget(self, source: str, text: str, diff: dict[str, Any], limits: dict[str, Any]) -> None:
        changed = sum(1 for item in diff["diff_lines"] if item.get("type") in {"added", "removed"})
        if changed > int(limits["max_changed_paragraphs"]) * 2: raise ImprovementPolicyError("IMPROVEMENT_BUDGET_EXCEEDED", "Too many paragraphs changed.")
        base = max(len(source), 1); added_chars = removed_chars = 0
        for tag, left_start, left_end, right_start, right_end in difflib.SequenceMatcher(a=source, b=text).get_opcodes():
            if tag in {"insert", "replace"}: added_chars += right_end - right_start
            if tag in {"delete", "replace"}: removed_chars += left_end - left_start
        added, removed = added_chars / base, removed_chars / base
        changed_ratio = max(added, removed)
        if changed_ratio > float(limits["max_changed_ratio"]) or added > float(limits["max_added_ratio"]) or removed > float(limits["max_deleted_ratio"]):
            raise ImprovementPolicyError("IMPROVEMENT_BUDGET_EXCEEDED", "Candidate exceeds the text-change budget.")

    def _save_candidate(self, request: dict[str, Any], text: str, diff: dict[str, Any]) -> dict[str, Any]:
        candidate_id = f"candidate_{uuid4().hex}"; root = f"data/evaluations/improvements/{request['improvement_id']}"
        path = f"{root}/{candidate_id}.md"; self.store.write_markdown(path, text)
        return {"candidate_id": candidate_id, "content_path": path, "content_hash": _hash(text), "created_at": _now(), "diff": diff,
                "patch_ids": [str(patch.get("patch_id")) for patch in request["plan"]["patches"]],
                "issue_map": [{"issue_id": item, "patch_indexes": [index for index, patch in enumerate(request["plan"]["patches"]) if item in patch.get("issue_ids", [])]} for item in request["issue_ids"]]}

    def _compare(self, baseline: dict[str, Any], candidate: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
        before = {item.get("dimension_id"): item.get("score") for item in baseline.get("dimensions", []) if isinstance(item, dict)}
        after = {item.get("dimension_id"): item.get("score") for item in candidate.get("dimensions", []) if isinstance(item, dict)}
        deltas = {key: round(float(after[key]) - float(before[key]), 2) for key in after if key in before and isinstance(after[key], (int, float)) and isinstance(before[key], (int, float))}
        overall = (candidate.get("overall_score") or 0) - (baseline.get("overall_score") or 0)
        major_regression = any(value <= -12 for value in deltas.values())
        recommendation = "qualified" if overall >= 0 and not major_regression and not candidate.get("unavailable_dimensions") else "review_required"
        if major_regression: recommendation = "rejected"
        return {"baseline_score": baseline.get("overall_score"), "candidate_score": candidate.get("overall_score"), "overall_delta": round(overall, 2), "dimension_deltas": deltas,
                "gate_before": baseline.get("gate_status"), "gate_after": "attention" if candidate.get("unavailable_dimensions") else "pass", "diff_summary": diff["summary"],
                "new_blocking_issues": [], "major_regression": major_regression, "recommendation": recommendation,
                "note": "Recommendation only; this stage never adopts or applies a candidate."}

    def _save(self, item: dict[str, Any]) -> None:
        root = f"data/evaluations/improvements/{item['improvement_id']}"; self.store.write_json(f"{root}/request.json", item)
        index = self._index(); rows = [row for row in index.get("improvements", []) if row.get("improvement_id") != item["improvement_id"]]
        rows.append({key: item.get(key) for key in ("improvement_id", "evaluation_id", "source_hash", "operation_id", "chapter_id", "state", "created_at")}); self.store.write_json("data/evaluations/improvements/index.json", {"improvements": rows})

    def _index(self) -> dict[str, Any]: return self.store.read_json("data/evaluations/improvements/index.json", default={"improvements": []}, expected_type=dict) or {"improvements": []}
    def _find_operation(self, operation_id: str) -> dict[str, Any] | None:
        row = next((item for item in self._index().get("improvements", []) if item.get("operation_id") == operation_id), None)
        return self.get(str(row["improvement_id"])) if row else None
    def _cancel(self, request: dict[str, Any]) -> dict[str, Any]: request.update({"state": "cancelled", "updated_at": _now(), "failure_code": "CANCELLED"}); self._save(request); return self.public(request)
