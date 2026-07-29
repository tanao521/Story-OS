from pathlib import Path

from system.simulator_loop_state import _scope_dict
from core.contracts.narrative_turn import NarrativeScope


def test_read_model_scope_exposes_compile_precondition_fingerprint():
    scope = _scope_dict(NarrativeScope("project_1", "main", "root"), 1, "manual_v001", "canon_1", "a" * 64)
    assert scope["source_fingerprint"] == "a" * 64


def test_candidate_detail_route_whitelists_scope_and_read_only_content():
    source = (Path(__file__).resolve().parents[1] / "web" / "narrative_chapter_routes.py").read_text(encoding="utf-8")
    assert 'safe["scope"]' in source
    assert 'safe["content"]' in source
    assert 'safe["evidence"]' in source


def test_approved_read_model_exposes_commit_authority_and_completed_stage(tmp_path):
    from tests._rc2_browser_fixture_server import setup_workspace
    from core.project_context import get_project_context
    from system.narrative_candidate_review_service import NarrativeCandidateReviewService
    from system.narrative_chapter_compiler import CompilationScope, NarrativeChapterCommitService, NarrativeChapterCompiler
    from system.simulator_loop_state import SimulatorLoopStateService

    info = setup_workspace(tmp_path)
    context = get_project_context(tmp_path / "projects" / info["project_id"])
    read = SimulatorLoopStateService(context)
    before = read.build(project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1).to_dict()
    scope = CompilationScope(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1,
        source_version_id=before["scope"]["source_version_id"],
        expected_source_fingerprint=before["scope"]["source_fingerprint"],
        expected_canon_revision_id=before["scope"]["canon_revision_id"],
        expected_branch_registry_revision=before["branch"]["registry_revision"],
    )
    candidate = NarrativeChapterCompiler(context).compile_candidate(operation_id="d2-test-compile", scope=scope)
    NarrativeCandidateReviewService(context).review_candidate(
        operation_id="d2-test-review", scope=scope, candidate_id=candidate["candidate_id"],
        candidate_version_id=candidate["candidate_version_id"], decision="approved", reviewer_id="test-reviewer",
    )
    approved = read.build(project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1).to_dict()
    assert approved["approval"]["status"] == "approved"
    assert approved["approval"]["can_commit"] is True
    NarrativeChapterCommitService(context).commit_candidate(
        operation_id="d2-test-commit", scope=scope, candidate_version_id=candidate["candidate_version_id"],
        ordered_turn_ids=["fixture-turn-1", "fixture-turn-2"],
    )
    completed = read.build(project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1).to_dict()
    assert completed["chapter_progression"]["completed"] is True
    assert completed["commit"]["durable_result"]["commit_id"]
