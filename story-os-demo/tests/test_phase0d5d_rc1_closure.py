import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fixture_faults_are_transport_only_and_audited():
    source = (ROOT / "tests" / "_rc2_browser_fixture_server.py").read_text(encoding="utf-8")
    for env_name in (
        "STORYOS_DRC_DROP_COMPILE_RESPONSE",
        "STORYOS_DRC_DROP_REVIEW_RESPONSE",
        "STORYOS_DRC_DROP_COMMIT_RESPONSE",
    ):
        assert env_name in source
    assert ".drc1_network_audit.json" in source
    assert "server_app = MutationAuditAndResponseDrop(app)" in source
    assert "raise asyncio.CancelledError" not in source


def test_response_loss_and_navigation_contracts_are_fail_closed():
    review = (ROOT / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    template = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'error.code = "RESPONSE_UNREADABLE"' in review
    assert "state.unknown.commit = true" in review
    assert 'id="simulator-progress-rail"' in template
    assert "Candidate rejected. Commit is unavailable." in review


def test_reject_keeps_candidate_and_source_immutable(tmp_path):
    from core.project_context import get_project_context
    from system.narrative_candidate_review_service import NarrativeCandidateReviewService
    from system.narrative_chapter_compiler import CompilationScope, NarrativeChapterCompiler
    from system.simulator_loop_state import SimulatorLoopStateService
    from tests._rc2_browser_fixture_server import setup_workspace

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
    source_path = context.data_dir / "manual" / "chapter_001_manual_v001.json"
    canon_index = context.data_dir / "canon_versions" / "chapter_001" / "index.json"
    source_before = source_path.read_bytes()
    canon_before = canon_index.read_bytes()
    candidate = NarrativeChapterCompiler(context).compile_candidate(operation_id="drc1-reject-compile", scope=scope)
    candidate_path = next(
        path for path in context.data_dir.rglob("*.json")
        if _is_candidate_payload(path, candidate["candidate_id"])
    )
    candidate_before = candidate_path.read_bytes()
    review = NarrativeCandidateReviewService(context).review_candidate(
        operation_id="drc1-reject-review", scope=scope, candidate_id=candidate["candidate_id"],
        candidate_version_id=candidate["candidate_version_id"], decision="rejected", reviewer_id="drc1",
        reason="fixture reject",
    )
    assert review["decision"] == "rejected"
    state = read.build(project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1).to_dict()
    assert state["approval"]["status"] == "rejected"
    assert state["approval"]["can_commit"] is False
    assert candidate_path.read_bytes() == candidate_before
    assert source_path.read_bytes() == source_before
    assert canon_index.read_bytes() == canon_before


def _is_candidate_payload(path: Path, candidate_id: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    provenance = payload.get("narrative_compilation")
    return (
        (payload.get("candidate_id") == candidate_id or (isinstance(provenance, dict) and provenance.get("candidate_id") == candidate_id))
        and bool(payload.get("manual_text"))
    )
