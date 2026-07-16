from __future__ import annotations

import pytest

from core.contracts import HashGuard
from core.contracts.adoption_contract import AdoptionContractError, AdoptionPreview, AdoptionRequest, AdoptionResult


def test_adoption_contracts_require_hashes_confirmation_and_valid_operation() -> None:
    digest = HashGuard.sha256_text("text")
    preview = AdoptionPreview("preview-1", "candidate-1", "draft_v001", digest, digest, digest, "2030-01-01T00:00:00+00:00")
    request = AdoptionRequest("adopt-1", preview.preview_id, preview.candidate_id, True, "author reviewed", 1)
    result = AdoptionResult(request.operation_id, "manual_v001", digest, False, "audit-1")
    assert request.to_operation_envelope(project_id="project", target_id="manual_v001", expected_hashes={"candidate_hash": digest}).operation_id == "adopt-1"
    assert result.new_hash == digest

    with pytest.raises(AdoptionContractError) as no_confirmation:
        AdoptionRequest("adopt-2", "preview-1", "candidate-1", False, "", 1)
    assert no_confirmation.value.code == "ADOPTION_CONFIRMATION_REQUIRED"
    with pytest.raises(AdoptionContractError) as invalid_operation:
        AdoptionRequest("bad operation", "preview-1", "candidate-1", True, "", 1)
    assert invalid_operation.value.code == "OPERATION_ID_INVALID"


def test_partial_adoption_contract_requires_stable_selected_patch_set() -> None:
    digest = HashGuard.sha256_text("text")
    patches = ("patch-a", "patch-b")
    patch_set_hash = HashGuard.sha256_json(patches)
    preview = AdoptionPreview("preview-partial", "candidate-1", "draft_v001", digest, digest, digest, "2030-01-01T00:00:00+00:00", "partial", patches, patch_set_hash)
    request = AdoptionRequest("partial-1", preview.preview_id, preview.candidate_id, True, "author reviewed", 1, "partial", patches, patch_set_hash)
    assert request.selected_patch_ids == patches
    with pytest.raises(AdoptionContractError) as invalid:
        AdoptionPreview("preview-whole", "candidate-1", "draft_v001", digest, digest, digest, "2030-01-01T00:00:00+00:00", "whole", ("patch-a",), "")
    assert invalid.value.code == "ADOPTION_PATCH_SELECTION_INVALID"
