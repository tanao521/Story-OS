from __future__ import annotations

from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.simulator_loop_state import SimulatorLoopStateService
from tests.test_phase0d5d1_review_authority import _candidate
from tests.test_phase0d5b_read_model import make_context


def test_read_model_exposes_durable_approval_flags(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    NarrativeCandidateReviewService(context).review_candidate(operation_id="approved", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id="root", source_version_id="manual_v001")
    assert state.approval["status"] == "approved"
    assert state.approval["can_commit"] is True

