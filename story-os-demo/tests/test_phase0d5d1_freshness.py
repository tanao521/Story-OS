from __future__ import annotations

import pytest
import json

from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.narrative_chapter_compiler import NarrativeCompilationError
from tests.test_phase0d5d1_review_authority import _candidate
from tests.test_phase0d5b_read_model import make_context


def test_review_rejects_stale_source_fingerprint(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    stale = type(scope)(**{**scope.__dict__, "expected_source_fingerprint": "different"})
    with pytest.raises(NarrativeCompilationError) as error:
        NarrativeCandidateReviewService(context).review_candidate(operation_id="stale", scope=stale, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    assert error.value.code in {"SOURCE_VERSION_STALE", "CANDIDATE_COLLISION"}


def test_review_rejects_changed_source_bytes_even_when_metadata_is_unchanged(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    candidate_path = context.manual_dir / "chapter_001_manual_v001.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["manual_text"] = "changed source bytes"
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NarrativeCompilationError) as error:
        NarrativeCandidateReviewService(context).review_candidate(
            operation_id="source-bytes", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer"
        )
    assert error.value.code == "SOURCE_VERSION_STALE"


@pytest.mark.parametrize("mutation,expected", [("missing", "CANDIDATE_COLLISION"), ("scope", "CANDIDATE_COLLISION")])
def test_candidate_scope_matrix_fails_closed(tmp_path, mutation, expected):
    context = make_context(tmp_path); scope = _candidate(context)
    candidate_path = context.manual_dir / "chapter_001_manual_v001.json"
    if mutation == "missing":
        candidate_path.unlink()
    else:
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        payload["candidate_scope"]["branch_id"] = "other-branch"
        candidate_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NarrativeCompilationError) as error:
        NarrativeCandidateReviewService(context).review_candidate(
            operation_id=f"matrix-{mutation}", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer"
        )
    assert error.value.code == expected


def test_review_supersede_race_fails_closed_before_publication(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    service = NarrativeCandidateReviewService(context)

    def supersede(point):
        if point == "after_first_freshness_validation":
            path = context.manual_dir / "chapter_001_manual_v001.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["review_status"] = "superseded"
            path.write_text(json.dumps(payload), encoding="utf-8")

    service._fault_injector = supersede
    with pytest.raises(NarrativeCompilationError) as error:
        service.review_candidate(operation_id="supersede-race", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    assert error.value.code == "CANDIDATE_SUPERSEDED"
    assert not (context.data_dir / "narrative_candidate_review" / "decisions" / "candidate-1.json").exists()


def test_review_archive_race_fails_closed_before_publication(tmp_path):
    context = make_context(tmp_path); scope = _candidate(context)
    service = NarrativeCandidateReviewService(context)

    def archive(point):
        if point == "after_first_freshness_validation":
            BranchLifecycleService(context).create(
                "replacement-race", {"project_id": context.root.name, "timeline_id": "main", "branch_id": "replacement", "display_name": "replacement"}
            )
            BranchLifecycleService(context).archive(
                "archive-race", {"project_id": context.root.name, "timeline_id": "main", "branch_id": scope.branch_id, "replacement_branch_id": "replacement"}
            )

    service._fault_injector = archive
    with pytest.raises(NarrativeCompilationError) as error:
        service.review_candidate(operation_id="archive-race", scope=scope, candidate_id="candidate-1", candidate_version_id="manual_v001", decision="approved", reviewer_id="reviewer")
    assert error.value.code == "BRANCH_ARCHIVED"
    assert not (context.data_dir / "narrative_candidate_review" / "decisions" / "candidate-1.json").exists()
