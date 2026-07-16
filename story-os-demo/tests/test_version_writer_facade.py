from __future__ import annotations

import json

import pytest

from core.contracts import HashGuard, ProjectRef
from core.contracts.adoption_contract import AdoptionRequest
from core.project_context import get_project_context
from system.version_manager import build_versioned_paths
from system.version_writer_facade import VersionWriterError, VersionWriterFacade
from system.revision_adapters import AdoptionAdapter, RevisionAdapter


def _setup(tmp_path):
    root = tmp_path / "version_writer_project"; root.mkdir()
    context = get_project_context(root)
    text = "candidate work version"
    source_hash, candidate_hash = HashGuard.sha256_text("source"), HashGuard.sha256_text(text)
    # This is the low-risk migration path: legacy payload -> adapters -> contracts -> facade.
    candidate = RevisionAdapter.candidate({
        "improvement_id": "revision-1", "source_hash": source_hash, "state": "qualified",
        "candidate": {"candidate_id": "candidate-1", "content_hash": candidate_hash},
        "comparison": {"recommendation": "qualified"},
    })
    request = AdoptionAdapter.request({
        "operation_id": "create-version-1", "preview_id": "preview-1", "candidate_id": candidate.candidate_id,
        "author_confirm": True, "review_reason": "author reviewed", "expected_current_version_revision": 1,
    })
    return context, ProjectRef.from_context(context), text, candidate, request


def test_temp_candidate_path_uses_adapter_contract_and_datastore_writer(tmp_path, monkeypatch) -> None:
    context, project, text, candidate, request = _setup(tmp_path)
    writer = VersionWriterFacade(context)
    calls = []
    original_json, original_text = writer.writer.write_json, writer.writer.write_text
    monkeypatch.setattr(writer.writer, "write_json", lambda **kwargs: (calls.append(kwargs["target_path"]), original_json(**kwargs))[1])
    monkeypatch.setattr(writer.writer, "write_text", lambda **kwargs: (calls.append(kwargs["target_path"]), original_text(**kwargs))[1])
    result = writer.create_work_version(project=project, chapter_id=1, source_type="draft", source_version=1, chapter_title="Test", candidate_text=text, candidate=candidate, adoption=request)
    expected = build_versioned_paths(1, "manual", 1, "data")
    manual = json.loads((context.root / expected["json_path"]).read_text(encoding="utf-8"))
    index = json.loads((context.root / "data/versions/chapter_001_versions.json").read_text(encoding="utf-8"))
    assert result.version_id == "manual_v001" and result.new_hash == candidate.candidate_hash
    assert manual["revision_contract"]["candidate_id"] == candidate.candidate_id
    assert index["selected"]["json_path"] == expected["json_path"] and result.audit_id
    assert expected["json_path"] in calls and expected["markdown_path"] in calls
    assert writer.create_work_version(project=project, chapter_id=1, source_type="draft", source_version=1, chapter_title="Test", candidate_text=text, candidate=candidate, adoption=request).replayed is True
    conflict = AdoptionRequest("create-version-1", "preview-1", candidate.candidate_id, True, "author reviewed", 2)
    with pytest.raises(VersionWriterError) as reused:
        writer.create_work_version(project=project, chapter_id=1, source_type="draft", source_version=1, chapter_title="Test", candidate_text=text, candidate=candidate, adoption=conflict)
    assert reused.value.code == "OPERATION_ID_CONFLICT"


def test_writer_rolls_back_new_files_when_index_write_fails(tmp_path, monkeypatch) -> None:
    context, project, text, candidate, request = _setup(tmp_path)
    writer = VersionWriterFacade(context); original = writer.writer.write_json
    def fail_index(**kwargs):
        if kwargs["target_path"].endswith("chapter_001_versions.json"):
            raise RuntimeError("injected index write failure")
        return original(**kwargs)
    monkeypatch.setattr(writer.writer, "write_json", fail_index)
    with pytest.raises(RuntimeError):
        writer.create_work_version(project=project, chapter_id=1, source_type="draft", source_version=1, chapter_title="Test", candidate_text=text, candidate=candidate, adoption=request)
    assert not (context.root / "data/manual/chapter_001_manual_v001.json").exists()
    assert not (context.root / "data/manual/chapter_001_manual_v001.md").exists()
    assert not (context.root / "data/audit/version_writer/version_writer_create-version-1.json").exists()


def test_legacy_draft_write_uses_one_facade_transaction_without_selecting(tmp_path) -> None:
    context, project, _, _, _ = _setup(tmp_path)
    writer = VersionWriterFacade(context)
    payload = {"chapter_id": 1, "version": 1, "version_label": "draft_v001", "draft_text": "draft text", "generation": {}}
    result = writer.write_legacy_work_version(project=project, chapter_id=1, kind="draft", version=1, payload=payload, markdown="# draft", operation_id="draft-write-1", select=False)
    assert result["version_id"] == "draft_v001" and result["selected"] is False
    assert (context.root / "data/drafts/chapter_001_draft_v001.json").exists()
    index = json.loads((context.root / "data/versions/chapter_001_versions.json").read_text(encoding="utf-8"))
    assert index["selected"] == {} and len(index["drafts"]) == 1
