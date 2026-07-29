"""RC4 authority-harness regression tests.

The completion assertion intentionally goes through the production compiler,
review gate and commit service.  It does not manufacture a completed read
model, DOM event, or completion JSON record.
"""
from __future__ import annotations

from pathlib import Path


def test_rc4_formal_completion_reactivates_authoritative_read_model(tmp_path: Path) -> None:
    from tests._rc2_browser_fixture_server import setup_workspace
    from core.project_context import get_project_context
    from system.narrative_candidate_review_service import NarrativeCandidateReviewService
    from system.narrative_chapter_compiler import (
        CompilationScope,
        NarrativeChapterCommitService,
        NarrativeChapterCompiler,
    )
    from system.simulator_loop_state import SimulatorLoopStateService

    info = setup_workspace(tmp_path)
    context = get_project_context(tmp_path / "projects" / info["project_id"])
    resolver = SimulatorLoopStateService(context)
    before = resolver.build(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1,
    ).to_dict()
    scope = CompilationScope(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1,
        source_version_id=before["scope"]["source_version_id"],
        expected_source_fingerprint=before["scope"]["source_fingerprint"],
        expected_canon_revision_id=before["scope"]["canon_revision_id"],
        expected_branch_registry_revision=before["branch"]["registry_revision"],
    )
    candidate = NarrativeChapterCompiler(context).compile_candidate(
        operation_id="rc4-formal-compile", scope=scope,
    )
    NarrativeCandidateReviewService(context).review_candidate(
        operation_id="rc4-formal-review", scope=scope,
        candidate_id=candidate["candidate_id"], candidate_version_id=candidate["candidate_version_id"],
        decision="approved", reviewer_id="rc4-harness",
    )
    result = NarrativeChapterCommitService(context).commit_candidate(
        operation_id="rc4-formal-commit", scope=scope,
        candidate_version_id=candidate["candidate_version_id"],
        ordered_turn_ids=["fixture-turn-1", "fixture-turn-2"],
    )
    after = resolver.build(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1,
    ).to_dict()

    assert result["status"] in {"committed", "already_committed", "committed_with_warnings"}
    assert after["chapter_progression"]["completed"] is True
    assert after["commit"]["durable_result"]["commit_id"]


def test_rc4_fixture_exposes_test_only_readiness_and_start_response_delays() -> None:
    source = (Path(__file__).resolve().parent / "_phase0d6c_fv_browser_fixture_server.py").read_text(encoding="utf-8")
    assert "STORYOS_RC4_READINESS_DELAY" in source
    assert "STORYOS_FV_START_DELAY" in source
    assert '"/api/chapter-progression/readiness"' in source
    assert '"/api/chapter-progression/start-turn"' in source
