from __future__ import annotations

from core.contracts import ErrorEnvelope, SafeResult
from web.view_models import api_error


def test_safe_error_envelope_redacts_sensitive_details_and_paths() -> None:
    result = ErrorEnvelope(
        code="DATA_STORAGE_FAILED",
        message="Write failed.",
        details={"path": "D:/novel/StoryOS/data/state.json", "traceback": "private", "nested": {"project_root": "D:/novel", "message": "safe"}},
    ).as_dict()

    assert result["details"] == {"nested": {"message": "safe"}}
    compatibility = api_error("Write failed at D:/novel/StoryOS/data/state.json", ["DATA_STORAGE_FAILED", "D:/novel/StoryOS/data/state.json"], details={"path": "D:/novel/StoryOS/data/state.json"})
    assert compatibility["ok"] is False and compatibility["error"]["code"] == "DATA_STORAGE_FAILED"
    assert "D:/novel" not in str(compatibility)


def test_safe_result_has_minimal_public_success_shape() -> None:
    assert SafeResult(data={"value": 1}).as_dict() == {"ok": True, "data": {"value": 1}}
