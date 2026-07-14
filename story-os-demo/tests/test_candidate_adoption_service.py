from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.data_store import DataWriteError
from evaluation_engine import EvaluationService
from evaluation_engine.candidate_adoption_service import CandidateAdoptionError, CandidateAdoptionService
from evaluation_engine.improvement_service import ImprovementService
from tests.test_evaluation_engine import _project


def _hash(text: str) -> str: return sha256(text.encode("utf-8")).hexdigest()


def _candidate(tmp_path: Path, state: str = "qualified"):
    protected = _project(tmp_path); context = get_project_context(tmp_path)
    report, _ = EvaluationService(context).generate({"target_type": "chapter_draft", "chapter_number": 1})
    source = "主角在雨夜发现线索。"; candidate_text = "主角在雨夜找到线索。"
    root = tmp_path / "data" / "evaluations" / "improvements" / "improvement_test"; root.mkdir(parents=True)
    (root / "candidate_test.md").write_text(candidate_text, encoding="utf-8")
    request = {"improvement_id": "improvement_test", "project_id": tmp_path.name, "chapter_id": 1, "evaluation_id": report["evaluation_id"],
               "source_hash": _hash(source), "source_ref": {"chapter_number": 1, "source_type": "draft", "source_version": 1}, "state": state,
               "candidate": {"candidate_id": "candidate_test", "content_path": "data/evaluations/improvements/improvement_test/candidate_test.md", "content_hash": _hash(candidate_text), "diff": {"summary": {"changed_ratio": .1}}},
               "evaluation": {"target_type": "chapter_candidate", "overall_score": 86}, "comparison": {"recommendation": state, "baseline_score": 80, "candidate_score": 86, "gate_before": "attention", "gate_after": "pass"}, "created_at": "now", "updated_at": "now"}
    ImprovementService(context)._save(request)
    return CandidateAdoptionService(context), request, protected, source


def _adopt_payload(preview: dict, request: dict, **extra):
    return {"preview_id": preview["preview_id"], "candidate_id": request["candidate"]["candidate_id"], "expected_current_version_id": preview["current_version_id"], "expected_current_version_revision": preview["current_version_revision"], "expected_current_content_hash": preview["current_content_hash"], "expected_candidate_hash": preview["candidate_content_hash"], "author_confirm": True, "review_reason": "作者已复核", "operation_id": "adopt-1", **extra}


def test_qualified_candidate_creates_new_manual_work_version_without_canon_change(tmp_path: Path) -> None:
    service, request, protected, source = _candidate(tmp_path); before = {name: path.read_bytes() for name, path in protected.items()}
    preview = service.preview(request["improvement_id"]); result, replayed = service.adopt(request["improvement_id"], _adopt_payload(preview, request))
    assert replayed is False and result["new_version"]["version_id"] == "manual_v001"
    manual = json.loads((tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").read_text(encoding="utf-8"))
    assert manual["manual_text"] == "主角在雨夜找到线索。"
    assert manual["quality_improvement"]["source_candidate_id"] == "candidate_test"
    assert before == {name: path.read_bytes() for name, path in protected.items()}
    assert json.loads((tmp_path / "data" / "versions" / "chapter_001_versions.json").read_text(encoding="utf-8"))["selected"]["source_type"] == "manual"
    assert service.improvements.get(request["improvement_id"])["state"] == "adopted"
    replay, replayed = service.adopt(request["improvement_id"], _adopt_payload(preview, request))
    assert replayed and replay["new_version"]["version_id"] == "manual_v001"


def test_review_required_requires_explicit_confirmation_and_reason(tmp_path: Path) -> None:
    service, request, _, _ = _candidate(tmp_path, "review_required"); preview = service.preview(request["improvement_id"])
    with pytest.raises(CandidateAdoptionError) as error:
        service.adopt(request["improvement_id"], _adopt_payload(preview, request, author_confirm=False, review_reason=""))
    assert error.value.code == "AUTHOR_REVIEW_REQUIRED"
    result, _ = service.adopt(request["improvement_id"], _adopt_payload(preview, request))
    assert result["request"]["state"] == "adopted"


def test_rejected_is_not_previewable_and_discard_preserves_candidate(tmp_path: Path) -> None:
    service, request, protected, _ = _candidate(tmp_path, "rejected")
    with pytest.raises(CandidateAdoptionError) as error: service.preview(request["improvement_id"])
    assert error.value.code == "CANDIDATE_REJECTED"
    result, replayed = service.discard(request["improvement_id"], {"candidate_id": "candidate_test", "expected_candidate_hash": request["candidate"]["content_hash"], "reason": "退化", "operation_id": "discard-1"})
    assert not replayed and result["state"] == "discarded"
    assert (tmp_path / request["candidate"]["content_path"]).exists()
    assert not (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()


def test_preview_rejects_source_and_revision_changes(tmp_path: Path) -> None:
    service, request, _, _ = _candidate(tmp_path); preview = service.preview(request["improvement_id"])
    draft = tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json"; payload = json.loads(draft.read_text(encoding="utf-8")); payload["draft_text"] = "已修改"; draft.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CandidateAdoptionError) as error: service.preview(request["improvement_id"])
    assert error.value.code == "CANDIDATE_SOURCE_CHANGED"


def test_revision_conflict_and_pointer_write_failure_leave_candidate_unadopted(tmp_path: Path, monkeypatch) -> None:
    service, request, _, _ = _candidate(tmp_path); preview = service.preview(request["improvement_id"])
    index_path = tmp_path / "data" / "versions" / "chapter_001_versions.json"; service.store.write_json("data/versions/chapter_001_versions.json", {"version_index": "1.5", "chapter_id": 1, "selection_revision": 2})
    with pytest.raises(CandidateAdoptionError) as error: service.adopt(request["improvement_id"], _adopt_payload(preview, request))
    assert error.value.code == "DRAFT_VERSION_REVISION_CONFLICT"
    preview = service.preview(request["improvement_id"])
    original = service.store.write_json
    def fail_pointer(path, value, **kwargs):
        if "data/versions/chapter_001_versions.json" in str(path): raise DataWriteError("injected pointer failure")
        return original(path, value, **kwargs)
    monkeypatch.setattr(service.store, "write_json", fail_pointer)
    with pytest.raises(DataWriteError): service.adopt(request["improvement_id"], _adopt_payload(preview, request, operation_id="adopt-failure"))
    assert not (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()
    assert service.improvements.get(request["improvement_id"])["state"] == "qualified"


def test_discard_replay_is_idempotent(tmp_path: Path) -> None:
    service, request, _, _ = _candidate(tmp_path); payload = {"candidate_id": "candidate_test", "expected_candidate_hash": request["candidate"]["content_hash"], "reason": "作者选择放弃", "operation_id": "discard-1"}
    first, replayed = service.discard(request["improvement_id"], payload); second, replayed_again = service.discard(request["improvement_id"], payload)
    assert first["state"] == second["state"] == "discarded" and not replayed and replayed_again


def test_candidate_state_write_failure_rolls_back_new_work_version(tmp_path: Path, monkeypatch) -> None:
    service, request, _, _ = _candidate(tmp_path); preview = service.preview(request["improvement_id"]); original_save = service.improvements._save
    def fail_adopt(item):
        if item.get("state") == "adopted": raise DataWriteError("injected candidate write failure")
        return original_save(item)
    monkeypatch.setattr(service.improvements, "_save", fail_adopt)
    with pytest.raises(DataWriteError): service.adopt(request["improvement_id"], _adopt_payload(preview, request))
    assert not (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()
    assert ImprovementService(service.context).get(request["improvement_id"])["state"] == "qualified"
    report = EvaluationService(service.context).detail(request["evaluation_id"])
    assert report["status"] == "current"
