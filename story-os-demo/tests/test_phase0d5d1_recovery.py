from __future__ import annotations

from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.narrative_chapter_compiler import NarrativeCompilationError
from tests.test_phase0d5d1_review_authority import _candidate
from tests.test_phase0d5b_read_model import make_context
import json
import pytest


class InjectedReviewFault(RuntimeError):
    pass


def test_missing_result_recovers_from_immutable_decision(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context); service = NarrativeCandidateReviewService(context)
    service.review_candidate(operation_id="recover-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    (context.data_dir / "narrative_candidate_review" / "operations" / "recover-1.result.json").unlink()
    result = NarrativeCandidateReviewService(context).review_candidate(operation_id="recover-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    assert result["decision"] == "approved"
    assert (context.data_dir / "narrative_candidate_review" / "operations" / "recover-1.result.json").exists()


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_authority_claim",
        "after_candidate_snapshot",
        "after_first_freshness_validation",
        "after_review_decision_publication",
        "after_durable_result_publication",
        "before_completed_phase_marker",
    ],
)
def test_six_point_review_recovery_is_idempotent(tmp_path, fault_point):
    context = make_context(tmp_path)
    scope = _candidate(context)
    service = NarrativeCandidateReviewService(context)

    def inject(point):
        if point == fault_point:
            raise InjectedReviewFault(point)

    service._fault_injector = inject
    with pytest.raises(InjectedReviewFault):
        service.review_candidate(operation_id="six-point", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")

    authority_path = context.data_dir / "narrative_candidate_review" / "operations" / "six-point.json"
    authority_bytes = authority_path.read_bytes()
    recovered = NarrativeCandidateReviewService(context).review_candidate(
        operation_id="six-point", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer"
    )
    assert recovered["decision"] == "approved"
    assert authority_path.read_bytes() == authority_bytes
    decisions = list((context.data_dir / "narrative_candidate_review" / "decisions").glob("*.json"))
    results = list((context.data_dir / "narrative_candidate_review" / "operations").glob("*.result.json"))
    assert len(decisions) == 1
    assert len(results) == 1
    assert json.loads((context.data_dir / "narrative_candidate_review" / "operations" / "six-point.phase.json").read_text(encoding="utf-8"))["phase"] == "COMPLETED"
    decision = json.loads(decisions[0].read_text(encoding="utf-8"))
    result = json.loads(results[0].read_text(encoding="utf-8"))
    assert decision["outcome_fingerprint"] == result["outcome_fingerprint"]
    assert decision["canonical_request_fingerprint"] == result["canonical_request_fingerprint"]


def test_corrupt_or_forked_review_chain_fails_closed(tmp_path):
    context = make_context(tmp_path)
    scope = _candidate(context)
    service = NarrativeCandidateReviewService(context)
    service.review_candidate(operation_id="chain-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    decision_path = context.data_dir / "narrative_candidate_review" / "decisions" / "candidate-1.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["decision"] = "rejected"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    with pytest.raises(NarrativeCompilationError) as error:
        NarrativeCandidateReviewService(context).review_for_candidate(scope, "candidate-1")
    assert error.value.code == "REVIEW_CHAIN_INVALID"
