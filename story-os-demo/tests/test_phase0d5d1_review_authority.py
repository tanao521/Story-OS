from __future__ import annotations

import json
import hashlib

import pytest

from core.contracts.narrative_turn import TimelineContext
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.narrative_chapter_compiler import CompilationScope, NarrativeCompilationError
from tests.test_phase0d5b_read_model import make_context, seed_branch


def _candidate(context):
    scope0 = seed_branch(context)
    revision = NarrativeBranchStore(context).get_registry_revision(TimelineContext(context.root.name, "main"))
    source_fp = hashlib.sha256(b"candidate").hexdigest()
    scope = CompilationScope(context.root.name, "main", scope0.branch_id, 1, "manual_v001", source_fp, "canon-1", revision)
    context.manual_dir.mkdir(parents=True, exist_ok=True)
    payload = {"chapter_id": 1, "version_label": "manual_v001", "manual_text": "candidate", "candidate_id": "candidate-1", "candidate_fingerprint": "candidate-fp", "candidate_scope": scope.__dict__, "source_version_id": "manual_v001", "source_fingerprint": source_fp, "canon_revision_id": "canon-1", "narrative_compilation": {"candidate_id": "candidate-1", "candidate_fingerprint": "candidate-fp", "scope": scope.__dict__}}
    (context.manual_dir / "chapter_001_manual_v001.json").write_text(json.dumps(payload), encoding="utf-8")
    return scope


def test_review_authority_is_immutable_and_replays(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context); service = NarrativeCandidateReviewService(context)
    result = service.review_candidate(operation_id="review-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer", reason="ready")
    authority = context.data_dir / "narrative_candidate_review" / "operations" / "review-1.json"
    original = authority.read_bytes()
    replay = NarrativeCandidateReviewService(context).review_candidate(operation_id="review-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer", reason="ready")
    assert replay["replayed"] is True
    assert result["decision"] == "approved"
    assert authority.read_bytes() == original


def test_first_writer_wins_and_conflicting_decision_fails(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context); service = NarrativeCandidateReviewService(context)
    service.review_candidate(operation_id="review-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="one")
    with pytest.raises(NarrativeCompilationError, match="immutable review decision"):
        service.review_candidate(operation_id="review-2", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="rejected", reviewer_id="two")
