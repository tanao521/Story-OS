from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from core.project_context import get_project_context
from evaluation_engine import EvaluationService
from evaluation_engine.candidate_adoption_service import CandidateAdoptionError, CandidateAdoptionService
from evaluation_engine.candidate_partial_adoption_service import CandidatePartialAdoptionService, PartialAdoptionError
from evaluation_engine.improvement_service import ImprovementService
from system.data_store import DataWriteError
from system.text_diff import build_text_diff
from tests.test_evaluation_engine import _project


def _hash(value: str) -> str: return sha256(value.encode("utf-8")).hexdigest()


def _partial_candidate(tmp_path: Path, state: str = "qualified"):
    protected = _project(tmp_path)
    source = "Alpha original.\n\nBeta original."
    (tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(json.dumps({"chapter_id": 1, "draft_text": source, "generation": {}}), encoding="utf-8")
    context = get_project_context(tmp_path)
    report, _ = EvaluationService(context).generate({"target_type": "chapter_draft", "chapter_number": 1})
    candidate_text = "Alpha improved.\n\nBeta improved."
    root = tmp_path / "data" / "evaluations" / "improvements" / "improvement_partial"; root.mkdir(parents=True)
    (root / "candidate_partial.md").write_text(candidate_text, encoding="utf-8")
    patches = [
        {"patch_id": "patch_alpha", "issue_ids": ["issue_alpha"], "paragraph_start": 1, "paragraph_end": 1, "anchor": "Alpha original.", "original_anchor": "Alpha original.", "replacement_text": "Alpha improved.", "action": "improve_readability", "risk": "low", "depends_on_patch_ids": [], "conflicts_with_patch_ids": []},
        {"patch_id": "patch_beta", "issue_ids": ["issue_beta"], "paragraph_start": 2, "paragraph_end": 2, "anchor": "Beta original.", "original_anchor": "Beta original.", "replacement_text": "Beta improved.", "action": "smooth_transition", "risk": "low", "depends_on_patch_ids": [], "conflicts_with_patch_ids": []},
    ]
    request = {"improvement_id": "improvement_partial", "project_id": tmp_path.name, "chapter_id": 1, "evaluation_id": report["evaluation_id"], "source_hash": _hash(source), "source_ref": {"chapter_number": 1, "source_type": "draft", "source_version": 1}, "state": state, "issue_ids": ["issue_alpha", "issue_beta"], "plan": {"patches": patches}, "candidate": {"candidate_id": "candidate_partial", "content_path": "data/evaluations/improvements/improvement_partial/candidate_partial.md", "content_hash": _hash(candidate_text), "diff": build_text_diff(source, candidate_text), "patch_ids": ["patch_alpha", "patch_beta"]}, "evaluation": {"target_type": "chapter_candidate", "overall_score": 86}, "comparison": {"recommendation": state, "baseline_score": 80, "candidate_score": 86, "gate_before": "attention", "gate_after": "pass"}, "created_at": "now", "updated_at": "now"}
    ImprovementService(context)._save(request)
    return CandidatePartialAdoptionService(context), request, protected, source


def _adopt_payload(preview: dict, **extra):
    return {"preview_id": preview["preview_id"], "candidate_id": preview["candidate_id"], "selected_patch_ids": preview["selected_patch_ids"], "expected_current_version_id": preview["current_version_id"], "expected_current_version_revision": preview["current_version_revision"], "expected_current_content_hash": preview["current_content_hash"], "expected_candidate_hash": preview["candidate_content_hash"], "expected_result_content_hash": preview["result_content_hash"], "author_confirm": True, "review_reason": "author checked partial result", "operation_id": "partial-adopt-1", **extra}


def test_preview_is_non_mutating_and_partial_adoption_only_applies_selected_patch(tmp_path: Path) -> None:
    service, request, protected, source = _partial_candidate(tmp_path)
    before = {name: path.read_bytes() for name, path in protected.items()}
    preview = service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"], "replacement_text": "client tampering is ignored"})
    assert preview["selected_patch_ids"] == ["patch_alpha"] and preview["unselected_patch_ids"] == ["patch_beta"]
    assert preview["result_content"] == "Alpha improved.\n\nBeta original."
    assert preview["resolved_issue_ids"] == ["issue_alpha"] and preview["remaining_issue_ids"] == ["issue_beta"]
    assert before == {name: path.read_bytes() for name, path in protected.items()}
    result, replayed = service.adopt(request["improvement_id"], _adopt_payload(preview))
    assert not replayed and result["new_version"]["version_id"] == "manual_v001"
    manual = json.loads((tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").read_text(encoding="utf-8"))
    assert manual["manual_text"] == "Alpha improved.\n\nBeta original."
    assert manual["quality_improvement_partial"]["source_type"] == "quality_improvement_partial"
    assert manual["quality_improvement_partial"]["selected_patch_ids"] == ["patch_alpha"]
    assert before == {name: path.read_bytes() for name, path in protected.items()}
    saved = service.improvements.get(request["improvement_id"])
    assert saved["state"] == "partially_adopted" and saved["partial_adoption"]["diff_preview_id"] == preview["preview_id"]
    replay, replayed = service.adopt(request["improvement_id"], _adopt_payload(preview))
    assert replayed and replay["new_version"]["version_id"] == "manual_v001"
    with pytest.raises(CandidateAdoptionError) as error:
        CandidateAdoptionService(service.context).adopt(request["improvement_id"], {"operation_id": "whole-adopt"})
    assert error.value.code == "CANDIDATE_ALREADY_PARTIALLY_ADOPTED"


def test_patch_validation_rejects_empty_duplicates_dependencies_conflicts_and_overlaps(tmp_path: Path) -> None:
    service, request, _, _ = _partial_candidate(tmp_path)
    cases = [([], "PARTIAL_ADOPTION_NO_PATCH_SELECTED"), (["patch_alpha", "patch_alpha"], "PARTIAL_ADOPTION_PATCH_CONFLICT"), (["missing"], "PARTIAL_ADOPTION_PATCH_NOT_FOUND")]
    for selected, code in cases:
        with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": selected})
        assert error.value.code == code
    item = service.improvements.get(request["improvement_id"]); item["plan"]["patches"][1]["depends_on_patch_ids"] = ["patch_alpha"]; service.improvements._save(item)
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_beta"]})
    assert error.value.code == "PARTIAL_ADOPTION_PATCH_DEPENDENCY_MISSING"
    item["plan"]["patches"][1]["depends_on_patch_ids"] = []; item["plan"]["patches"][1]["conflicts_with_patch_ids"] = ["patch_alpha"]; service.improvements._save(item)
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha", "patch_beta"]})
    assert error.value.code == "PARTIAL_ADOPTION_PATCH_CONFLICT"
    item["plan"]["patches"][1]["conflicts_with_patch_ids"] = []; item["plan"]["patches"][1]["paragraph_start"] = 1; service.improvements._save(item)
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha", "patch_beta"]})
    assert error.value.code == "PARTIAL_ADOPTION_PATCH_OVERLAP"


def test_patch_selection_order_is_normalized_and_must_match_candidate_diff(tmp_path: Path) -> None:
    service, request, _, _ = _partial_candidate(tmp_path)
    first = service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha", "patch_beta"]})
    second = service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_beta", "patch_alpha"]})
    assert first["selected_patch_ids"] == second["selected_patch_ids"] == ["patch_alpha", "patch_beta"]
    assert first["result_content_hash"] == second["result_content_hash"]
    result, _ = service.adopt(request["improvement_id"], _adopt_payload(second, selected_patch_ids=["patch_beta", "patch_alpha"]))
    assert result["new_version"]["content_hash"] == second["result_content_hash"]
    service, request, _, _ = _partial_candidate(tmp_path / "bad-diff")
    item = service.improvements.get(request["improvement_id"]); item["candidate"]["diff"] = {"summary": {}, "diff_lines": []}; service.improvements._save(item)
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"]})
    assert error.value.code == "PARTIAL_ADOPTION_PATCH_NOT_ELIGIBLE"


def test_preview_and_confirmation_detect_source_preview_result_and_review_staleness(tmp_path: Path) -> None:
    service, request, _, _ = _partial_candidate(tmp_path, "review_required")
    preview = service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"]})
    with pytest.raises(PartialAdoptionError) as error: service.adopt(request["improvement_id"], _adopt_payload(preview, author_confirm=False, review_reason=""))
    assert error.value.code == "PARTIAL_ADOPTION_REVIEW_REASON_REQUIRED"
    with pytest.raises(PartialAdoptionError) as error: service.adopt(request["improvement_id"], _adopt_payload(preview, expected_result_content_hash="tampered"))
    assert error.value.code == "PARTIAL_ADOPTION_RESULT_HASH_MISMATCH"
    (tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(json.dumps({"chapter_id": 1, "draft_text": "changed source", "generation": {}}), encoding="utf-8")
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"]})
    assert error.value.code == "PARTIAL_ADOPTION_SOURCE_CHANGED"


def test_partial_adoption_is_project_scoped(tmp_path: Path) -> None:
    service, request, _, _ = _partial_candidate(tmp_path)
    item = service.improvements.get(request["improvement_id"]); item["project_id"] = "another-project"; service.improvements._save(item)
    with pytest.raises(PartialAdoptionError) as error: service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"]})
    assert error.value.code == "PARTIAL_ADOPTION_PROJECT_MISMATCH"


def test_state_write_failure_rolls_back_partial_manual_version(tmp_path: Path, monkeypatch) -> None:
    service, request, _, _ = _partial_candidate(tmp_path)
    preview = service.preview(request["improvement_id"], {"selected_patch_ids": ["patch_alpha"]})
    original_save = service.improvements._save
    def fail_partial(item):
        if item.get("state") == "partially_adopted": raise DataWriteError("injected state write failure")
        return original_save(item)
    monkeypatch.setattr(service.improvements, "_save", fail_partial)
    with pytest.raises(DataWriteError): service.adopt(request["improvement_id"], _adopt_payload(preview))
    assert not (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()
    assert ImprovementService(service.context).get(request["improvement_id"])["state"] == "qualified"
