from __future__ import annotations

import pytest

from core.contracts import HashExpectation, HashGuard, SafetyContractError


def test_hash_guard_requires_complete_sha_and_normalizes_case(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("safe", encoding="utf-8")
    digest = HashGuard.file_sha256(target)

    result = HashGuard.validate_target(target, HashExpectation(expected_sha256=digest.upper()))
    assert result.matched and result.actual_sha256 == digest
    with pytest.raises(SafetyContractError) as short:
        HashExpectation(expected_sha256=digest[:16])
    assert short.value.code == "HASH_INVALID_FORMAT"
    with pytest.raises(SafetyContractError) as missing_expectation:
        HashExpectation()
    assert missing_expectation.value.code == "HASH_EXPECTATION_REQUIRED"


def test_hash_guard_rejects_missing_targets_and_candidate_mismatches(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    digest = "a" * 64
    with pytest.raises(SafetyContractError) as absent:
        HashGuard.validate_target(missing, HashExpectation(expected_sha256=digest))
    assert absent.value.code == "HASH_TARGET_NOT_FOUND"
    assert HashGuard.validate_target(missing, HashExpectation.for_new_target()).target_exists is False

    with pytest.raises(SafetyContractError) as candidate:
        HashGuard.validate_candidate("b" * 64, "c" * 64)
    assert candidate.value.code == "HASH_CANDIDATE_MISMATCH"


def test_hash_guard_rejects_mismatch_without_treating_missing_as_match(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(SafetyContractError) as mismatch:
        HashGuard.validate_target(target, HashExpectation(expected_sha256="0" * 64))
    assert mismatch.value.code == "HASH_MISMATCH"
