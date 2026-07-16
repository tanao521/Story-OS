from __future__ import annotations

from core.contracts import HashGuard
from core.project_context import get_project_context
from system.version_adoption_service import VersionAdoptionService


class _Improvements:
    def __init__(self, request): self.request = request
    def get(self, request_id): return self.request


class _WholeAdapter:
    def __init__(self, request): self.improvements, self.called = _Improvements(request), []
    def _legacy_adopt(self, request_id, payload): self.called.append(("whole", request_id, payload)); return {"request": self.improvements.request}, False
    def _legacy_discard(self, request_id, payload): self.called.append(("discard", request_id, payload)); return self.improvements.request, False
    def _legacy_preview(self, request_id): return {"preview_id": "preview-1", "candidate_id": "candidate-1", "expected_source_version_id": "draft_v001", "expected_source_hash": self.improvements.request["source_hash"], "candidate_content_hash": self.improvements.request["candidate"]["content_hash"], "expires_at": "2030-01-01T00:00:00+00:00"}


def test_unified_service_forwards_commands_with_one_operation_fingerprint(tmp_path) -> None:
    root = tmp_path / "project"; root.mkdir(); context = get_project_context(root)
    source_hash, candidate_hash = HashGuard.sha256_text("source"), HashGuard.sha256_text("candidate")
    request = {"improvement_id": "improvement-1", "project_id": root.name, "source_hash": source_hash, "state": "qualified", "comparison": {"recommendation": "qualified"}, "candidate": {"candidate_id": "candidate-1", "content_hash": candidate_hash}}
    legacy = _WholeAdapter(request); service = VersionAdoptionService(context, whole_service=legacy)
    result, replayed = service.adopt_whole("improvement-1", {"operation_id": "adopt-1", "author_confirm": True, "review_reason": "reviewed"})
    assert not replayed and result["request"] is request
    assert legacy.called[0][2]["__operation_fingerprint"]
    assert service.preview_whole("improvement-1")["preview_id"] == "preview-1"
