from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from tests.test_phase0d5d1_review_authority import _candidate
from tests.test_phase0d5b_read_model import make_context


def test_concurrent_first_writer_wins(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    def decide(operation_id, decision):
        try:
            return NarrativeCandidateReviewService(context).review_candidate(operation_id=operation_id, scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision=decision, reviewer_id=operation_id)
        except Exception as exc:
            return getattr(exc, "code", type(exc).__name__)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: decide(*args), [("approve", "approved"), ("reject", "rejected")]))
    assert sum(isinstance(item, dict) for item in results) == 1


def test_concurrent_approve_approve_has_one_effective_decision(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)

    def decide(operation_id):
        try:
            return NarrativeCandidateReviewService(context).review_candidate(
                operation_id=operation_id, scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id=operation_id
            )
        except Exception as exc:
            return getattr(exc, "code", type(exc).__name__)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["approve-a", "approve-b"]))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert any(item in {"REVIEW_ALREADY_DECIDED", "REVIEW_DECISION_CONFLICT"} for item in results if isinstance(item, str))
    decision_files = list((context.data_dir / "narrative_candidate_review" / "decisions").glob("*.json"))
    assert len(decision_files) == 1
    assert json.loads(decision_files[0].read_text(encoding="utf-8"))["decision"] == "approved"
