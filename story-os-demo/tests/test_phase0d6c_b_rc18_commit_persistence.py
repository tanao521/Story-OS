from __future__ import annotations

from pathlib import Path


def test_returned_commit_id_matches_authoritative_read_model(tmp_path: Path) -> None:
    from core.project_context import get_project_context
    from system.narrative_candidate_review_service import NarrativeCandidateReviewService
    from system.narrative_chapter_compiler import (
        CompilationScope,
        NarrativeChapterCommitService,
        NarrativeChapterCompiler,
    )
    from system.simulator_loop_state import SimulatorLoopStateService
    from tests._rc2_browser_fixture_server import setup_workspace

    info = setup_workspace(tmp_path)
    context = get_project_context(tmp_path / "projects" / info["project_id"])
    read_model = SimulatorLoopStateService(context)
    before = read_model.build(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1
    ).to_dict()
    scope = CompilationScope(
        project_id=info["project_id"],
        timeline_id="tl-main",
        branch_id="root",
        chapter_id=1,
        source_version_id=before["scope"]["source_version_id"],
        expected_source_fingerprint=before["scope"]["source_fingerprint"],
        expected_canon_revision_id=before["scope"]["canon_revision_id"],
        expected_branch_registry_revision=before["branch"]["registry_revision"],
    )
    candidate = NarrativeChapterCompiler(context).compile_candidate(
        operation_id="rc18-compile", scope=scope
    )
    NarrativeCandidateReviewService(context).review_candidate(
        operation_id="rc18-review",
        scope=scope,
        candidate_id=candidate["candidate_id"],
        candidate_version_id=candidate["candidate_version_id"],
        decision="approved",
        reviewer_id="rc18-test",
    )
    returned = NarrativeChapterCommitService(context).commit_candidate(
        operation_id="rc18-commit",
        scope=scope,
        candidate_version_id=candidate["candidate_version_id"],
        ordered_turn_ids=["fixture-turn-1", "fixture-turn-2"],
    )
    persisted = read_model.build(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1
    ).to_dict()

    assert persisted["chapter_progression"]["completed"] is True
    assert returned["commit_id"] == persisted["commit"]["durable_result"]["commit_id"]
