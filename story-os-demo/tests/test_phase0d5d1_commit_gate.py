from __future__ import annotations

import pytest

from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.narrative_chapter_compiler import NarrativeCompilationError, NarrativeChapterCommitService
from system.chapter_commit_service import CommitStatus
from tests.test_phase0d5d1_review_authority import _candidate
from tests.test_phase0d5b_read_model import make_context


def test_pending_and_rejected_candidates_cannot_pass_commit_gate(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context); service = NarrativeCandidateReviewService(context)
    with pytest.raises(NarrativeCompilationError) as pending:
        service.assert_commit_approved(scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", candidate_fingerprint="candidate-fp")
    assert pending.value.code == "CANDIDATE_NOT_APPROVED"
    service.review_candidate(operation_id="reject-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="rejected", reviewer_id="reviewer")
    with pytest.raises(NarrativeCompilationError) as rejected:
        service.assert_commit_approved(scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", candidate_fingerprint="candidate-fp")
    assert rejected.value.code == "CANDIDATE_NOT_APPROVED"


def test_approved_candidate_passes_durable_gate(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context); service = NarrativeCandidateReviewService(context)
    service.review_candidate(operation_id="approve-1", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    assert service.assert_commit_approved(scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", candidate_fingerprint="candidate-fp")["decision"] == "approved"


def test_pending_and_rejected_commit_gate_never_calls_chapter_commit_service(tmp_path, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("ChapterCommitService must not be called")

    monkeypatch.setattr("system.narrative_chapter_compiler.ChapterCommitService.commit_chapter", forbidden)
    context = make_context(tmp_path); scope = _candidate(context)
    compiler = NarrativeChapterCommitService(context)
    with pytest.raises(NarrativeCompilationError):
        compiler.commit_candidate(operation_id="pending-commit", scope=scope, candidate_version_id="manual_v001")
    NarrativeCandidateReviewService(context).review_candidate(operation_id="reject-gate", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="rejected", reviewer_id="reviewer")
    with pytest.raises(NarrativeCompilationError):
        compiler.commit_candidate(operation_id="rejected-commit", scope=scope, candidate_version_id="manual_v001")
    assert calls == []


def test_valid_commit_calls_existing_service_once_and_replays_durable_result(tmp_path, monkeypatch):
    calls = []

    class FakeResult:
        status = CommitStatus.COMMITTED
        commit_id = "commit-1"
        canon_revision_id = "canon-2"

    def commit_once(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResult()

    monkeypatch.setattr("system.narrative_chapter_compiler.ChapterCommitService.commit_chapter", commit_once)
    context = make_context(tmp_path); scope = _candidate(context)
    NarrativeCandidateReviewService(context).review_candidate(operation_id="approve-gate", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    service = NarrativeChapterCommitService(context)
    first = service.commit_candidate(operation_id="commit-once", scope=scope, candidate_version_id="manual_v001")
    assert first["status"] == "committed"
    assert len(calls) == 1

    # A durable commit result is the recovery authority, even if the review
    # chain later becomes unreadable.
    decision_path = context.data_dir / "narrative_candidate_review" / "decisions" / "candidate-1.json"
    decision_path.unlink()
    replay = NarrativeChapterCommitService(context).commit_candidate(operation_id="commit-once", scope=scope, candidate_version_id="manual_v001")
    assert replay["status"] == "committed"
    assert replay["replayed"] is True
    assert len(calls) == 1
