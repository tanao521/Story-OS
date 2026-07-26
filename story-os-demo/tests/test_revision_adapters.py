from __future__ import annotations

from core.contracts import HashGuard
from system.revision_adapters import AdoptionAdapter, LegacyOperationAdapter, RevisionAdapter, VersionAdapter


def test_adapters_preserve_legacy_fields_and_keep_revision_adoption_separate() -> None:
    source_hash, candidate_hash = HashGuard.sha256_text("source"), HashGuard.sha256_text("candidate")
    legacy_request = {
        "improvement_id": "improvement-1", "project_id": "project", "chapter_id": 1,
        "source_ref": {"source_type": "draft", "source_version": 1}, "source_hash": source_hash,
        "issue_ids": ["issue-1"], "mode": "restricted_candidate", "state": "qualified",
        "candidate": {"candidate_id": "candidate-1", "content_hash": candidate_hash},
        "comparison": {"recommendation": "qualified"},
    }
    revision = RevisionAdapter.request(legacy_request)
    candidate = RevisionAdapter.candidate(legacy_request)
    patch = RevisionAdapter.patch({"patch_id": "patch-1", "anchor": "before", "risk": "low"}, candidate_id=candidate.candidate_id, source_hash=source_hash, candidate_hash=candidate_hash)
    assert revision.source_version == "draft_v001" and candidate.status == "qualified" and patch.before_text_hash == source_hash

    preview = AdoptionAdapter.preview({"preview_id": "preview-1", "candidate_id": "candidate-1", "expected_source_version_id": "draft_v001", "expected_source_hash": source_hash, "candidate_content_hash": candidate_hash, "expires_at": "2030-01-01T00:00:00+00:00"})
    request = AdoptionAdapter.request({"operation_id": "adopt-1", "preview_id": preview.preview_id, "candidate_id": preview.candidate_id, "author_confirm": True, "review_reason": "reviewed", "expected_current_version_revision": 1})
    envelope = LegacyOperationAdapter.envelope(operation_id=request.operation_id, project_id="project", target_type="version", target_id="manual_v001", expected_hashes={"candidate_hash": candidate_hash}, reason="reviewed")
    result = VersionAdapter.result({"new_version": {"version_id": "manual_v001", "content_hash": candidate_hash}}, operation_id=request.operation_id, audit_id="audit-1")
    assert preview.expected_result_hash == candidate_hash and envelope.operation_id == "adopt-1" and result.version_id == "manual_v001"
