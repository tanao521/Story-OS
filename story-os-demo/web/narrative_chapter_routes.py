from __future__ import annotations

from typing import Any
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.narrative_chapter_compiler import CompilationScope, NarrativeCompilationError, NarrativeChapterCompiler, NarrativeChapterCommitService
from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.project_identity_resolver import ProjectIdentityResolutionError, ProjectIdentityResolver

router = APIRouter(prefix="/api/narrative-chapter", tags=["narrative-chapter"])
_HEADERS = {"Cache-Control": "no-store"}

def _project_boundary(project_id: str):
    """Resolve formal UUIDs once at the legacy storage boundary."""
    try:
        uuid.UUID(project_id)
    except (ValueError, AttributeError):
        context = get_project_context()
        if project_id != context.root.name:
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found")
        return context, project_id
    identity = ProjectIdentityResolver().resolve(project_id)
    return identity.context, identity.project_id

def _scope(data: dict[str, Any]) -> CompilationScope:
    try:
        chapter_id = int(data.get("chapter_id") or 0)
    except (TypeError, ValueError) as exc:
        raise NarrativeCompilationError("REVIEW_SCOPE_REQUIRED", "A valid chapter scope is required.") from exc
    return CompilationScope(
        project_id=str(data.get("project_id") or ""), timeline_id=str(data.get("timeline_id") or ""), branch_id=str(data.get("branch_id") or ""),
        chapter_id=chapter_id, source_version_id=data.get("source_version_id"), expected_source_fingerprint=data.get("expected_source_fingerprint"),
        expected_canon_revision_id=str(data.get("expected_canon_revision_id") or ""), expected_branch_registry_revision=str(data.get("expected_branch_registry_revision") or ""),
    )

def _error(exc: Exception) -> JSONResponse:
    raw_code = getattr(exc, "code", None)
    known_codes = {
        "REVIEW_SCOPE_REQUIRED", "REVIEW_OPERATION_CONFLICT", "REVIEW_DECISION_CONFLICT", "REVIEW_ALREADY_DECIDED",
        "REVIEW_CHAIN_INVALID", "CANDIDATE_COLLISION", "CANDIDATE_SUPERSEDED", "CANDIDATE_ALREADY_COMMITTED", "CANDIDATE_NOT_APPROVED", "CANDIDATE_REVIEW_STALE",
        "SOURCE_VERSION_STALE", "CANON_REVISION_STALE", "BRANCH_ARCHIVED", "BRANCH_NOT_ACTIVE", "COMPILATION_SCOPE_REQUIRED",
        "COMMIT_OPERATION_CONFLICT", "COMMIT_RECOVERY_REQUIRED", "NO_ELIGIBLE_TURNS", "TURN_ALREADY_INCLUDED",
    }
    code = raw_code if isinstance(raw_code, str) and raw_code in known_codes else "NARRATIVE_OPERATION_FAILED"
    messages = {
        "REVIEW_SCOPE_REQUIRED": "Review request is invalid.",
        "REVIEW_OPERATION_CONFLICT": "Review operation conflicts with an existing request.",
        "REVIEW_DECISION_CONFLICT": "Candidate already has a conflicting review decision.",
        "REVIEW_ALREADY_DECIDED": "Candidate already has a durable review decision.",
        "REVIEW_CHAIN_INVALID": "Review authority chain is invalid.",
        "CANDIDATE_COLLISION": "Candidate is unavailable or ambiguous.",
        "CANDIDATE_SUPERSEDED": "Candidate has been superseded.",
        "CANDIDATE_ALREADY_COMMITTED": "Candidate has already been committed.",
        "CANDIDATE_NOT_APPROVED": "Candidate is not approved for commit.",
        "CANDIDATE_REVIEW_STALE": "Candidate review is stale.",
        "SOURCE_VERSION_STALE": "Candidate source is stale.",
        "CANON_REVISION_STALE": "Canon expectation is stale.",
        "BRANCH_ARCHIVED": "Candidate branch is archived.",
        "BRANCH_NOT_ACTIVE": "Candidate branch is not active.",
        "COMPILATION_SCOPE_REQUIRED": "Narrative scope is invalid.",
        "COMMIT_OPERATION_CONFLICT": "Commit operation conflicts with an existing request.",
        "COMMIT_RECOVERY_REQUIRED": "Commit recovery is required.",
        "NO_ELIGIBLE_TURNS": "No eligible Turns are available.",
        "TURN_ALREADY_INCLUDED": "Turn is already included.",
        "NARRATIVE_OPERATION_FAILED": "Narrative operation failed.",
    }
    status = 400 if code == "REVIEW_SCOPE_REQUIRED" else 409
    return JSONResponse({"ok": False, "error": {"code": code, "message": messages[code]}, "result": {}, "warnings": [], "errors": [code]}, status_code=status, headers=_HEADERS)

@router.post("/compile")
async def compile_candidate(request: Request):
    try:
        data = await request.json(); scope = _scope(data)
        context, canonical_project_id = _project_boundary(scope.project_id)
        result = NarrativeChapterCompiler(context, canonical_project_id=canonical_project_id).compile_candidate(operation_id=str(data.get("operation_id") or ""), scope=scope)
        return JSONResponse({"ok": True, "result": result, "warnings": [], "errors": []}, headers=_HEADERS)
    except Exception as exc:
        return _error(exc)

@router.post("/commit")
async def commit_candidate(request: Request):
    try:
        data = await request.json(); scope = _scope(data)
        context, canonical_project_id = _project_boundary(scope.project_id)
        result = NarrativeChapterCommitService(context, canonical_project_id=canonical_project_id).commit_candidate(operation_id=str(data.get("operation_id") or ""), scope=scope, candidate_version_id=str(data.get("candidate_version_id") or ""), ordered_turn_ids=list(data.get("ordered_turn_ids") or []))
        return JSONResponse({"ok": True, "result": result, "warnings": [], "errors": []}, headers=_HEADERS)
    except Exception as exc:
        return _error(exc)

@router.post("/candidates/{candidate_id}/review")
async def review_candidate(candidate_id: str, request: Request):
    try:
        data = await request.json(); scope = _scope(data)
        context, canonical_project_id = _project_boundary(scope.project_id)
        result = NarrativeCandidateReviewService(context, canonical_project_id=canonical_project_id).review_candidate(
            operation_id=str(data.get("operation_id") or ""), scope=scope, candidate_id=candidate_id,
            candidate_version_id=data.get("candidate_version_id"), decision=str(data.get("decision") or ""),
            reviewer_id=str(data.get("reviewer_id") or ""), reason=str(data.get("reason") or ""),
        )
        return JSONResponse({"ok": True, "result": result, "warnings": [], "errors": []}, headers=_HEADERS)
    except Exception as exc:
        return _error(exc)

@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    try:
        context = get_project_context()
        for path in sorted((context.data_dir / "manual").glob("chapter_*_manual_v*.json")):
            import json
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("candidate_id") == candidate_id or (isinstance(payload.get("narrative_compilation"), dict) and payload["narrative_compilation"].get("candidate_id") == candidate_id):
                provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
                safe = {k: payload.get(k) for k in ("candidate_id", "candidate_fingerprint", "version_label", "review_status", "chapter_id", "source_version_id", "canon_revision_id")}
                safe["candidate_id"] = safe["candidate_id"] or provenance.get("candidate_id")
                safe["candidate_fingerprint"] = safe["candidate_fingerprint"] or provenance.get("candidate_fingerprint")
                scope_data = payload.get("candidate_scope") or (payload.get("narrative_compilation") or {}).get("scope")
                if isinstance(scope_data, dict):
                    safe["scope"] = {key: scope_data.get(key) for key in ("project_id", "timeline_id", "branch_id", "chapter_id", "source_version_id", "expected_canon_revision_id", "expected_branch_registry_revision")}
                    review = NarrativeCandidateReviewService(context).review_for_candidate(_scope(scope_data), candidate_id)
                    safe["review"] = {k: review.get(k) for k in ("review_id", "decision", "reviewer_id", "reason", "decided_at", "outcome_fingerprint")} if review else None
                included_turns = provenance.get("ordered_turn_ids") or payload.get("included_turn_ids") or []
                safe["evidence"] = {"included_turn_ids": [str(value) for value in included_turns if isinstance(value, (str, int))]}
                content = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
                safe["content"] = {"kind": "compiled_candidate" if content else "missing", "text": content or None}
                return JSONResponse({"ok": True, "result": safe, "warnings": [], "errors": []}, headers=_HEADERS)
        raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate not found.")
    except Exception as exc:
        return _error(exc)
