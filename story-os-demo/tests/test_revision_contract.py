from __future__ import annotations

import pytest

from core.contracts import HashGuard
from core.contracts.revision_contract import RevisionCandidate, RevisionContractError, RevisionPatch, RevisionRequest


def test_revision_contracts_validate_fields_hashes_and_status_boundaries() -> None:
    digest = HashGuard.sha256_text("text")
    request = RevisionRequest("revision-1", "project", "chapter_draft", "1", "draft_v001", ("issue-1",), "bounded", "low")
    candidate = RevisionCandidate("candidate-1", request.revision_id, digest, digest, "local", "qualified")
    patch = RevisionPatch("patch-1", candidate.candidate_id, {"anchor": "line"}, digest, digest, "low", (), ())
    assert request.issue_refs == ("issue-1",) and candidate.status == "qualified" and patch.location["anchor"] == "line"

    with pytest.raises(RevisionContractError) as invalid_status:
        RevisionCandidate("candidate-2", "revision-1", digest, digest, "local", "adopted")
    assert invalid_status.value.code == "REVISION_CANDIDATE_STATUS_INVALID"
    with pytest.raises(RevisionContractError) as invalid_hash:
        RevisionPatch("patch-2", "candidate-1", {"anchor": "line"}, "short", digest, "low", (), ())
    assert invalid_hash.value.code == "REVISION_HASH_INVALID"
