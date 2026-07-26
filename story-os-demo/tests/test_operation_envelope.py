from __future__ import annotations

import pytest

from core.contracts import OperationEnvelope, OperationEnvelopeError


def _valid(**changes):
    value = {
        "operation_id": "operation-1", "operation_type": "write_json", "project_id": "project-a",
        "target_type": "test_artifact", "target_id": "artifact-1", "expected_hashes": {"source": "a" * 64},
        "confirmed": True, "reason": "test", "requested_at": "2026-07-16T00:00:00+00:00",
    }
    value.update(changes)
    return OperationEnvelope(**value)


def test_operation_envelope_validates_request_and_has_stable_fingerprint() -> None:
    first = _valid()
    second = _valid(requested_at="2026-07-16T01:00:00+00:00")
    assert first.fingerprint() == second.fingerprint()
    assert first.expected_hashes["source"] == "a" * 64


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"operation_id": ""}, "OPERATION_ID_INVALID"),
        ({"operation_id": "x" * 129}, "OPERATION_ID_INVALID"),
        ({"operation_id": "bad id"}, "OPERATION_ID_INVALID"),
        ({"operation_type": "bad-type"}, "OPERATION_TYPE_INVALID"),
        ({"target_type": "bad-type"}, "TARGET_TYPE_INVALID"),
        ({"confirmed": False}, "OPERATION_CONFIRMATION_REQUIRED"),
        ({"risk_level": "high", "reason": ""}, "OPERATION_REASON_REQUIRED"),
        ({"expected_hashes": {"source": "short"}}, "HASH_INVALID_FORMAT"),
    ],
)
def test_operation_envelope_rejects_invalid_input(changes, code) -> None:
    with pytest.raises(OperationEnvelopeError) as error:
        _valid(**changes)
    assert error.value.code == code
