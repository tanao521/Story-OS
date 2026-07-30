from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.chapter_assembly_evidence_service import (
    ChapterAssemblyEvidenceError,
    ChapterAssemblyEvidenceScope,
    ChapterAssemblyEvidenceService,
)


def _write_version(root: Path, text: str, *, version_label: str = "manual_v001") -> Path:
    path = root / "data" / "manual" / "chapter_001_manual_v001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "chapter_id": 1, "version": 1, "version_label": version_label,
        "manual_text": text, "review_status": "pending",
    }), encoding="utf-8")
    return path


def _project(tmp_path: Path) -> tuple[Path, ChapterAssemblyEvidenceScope]:
    (tmp_path / "data" / "chapters").mkdir(parents=True)
    (tmp_path / "data" / "state.json").write_text('{"current_chapter": 1}', encoding="utf-8")
    (tmp_path / "data" / "chapters" / "chapter_001.md").write_text("已提交章节不得变更。", encoding="utf-8")
    _write_version(tmp_path, "第一章的确切正文。")
    registry = tmp_path / "data" / "branches" / "main" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "project_id": tmp_path.name, "timeline_id": "main", "active_branch_id": "main", "revision": "1",
    }), encoding="utf-8")
    scope = ChapterAssemblyEvidenceScope(
        project_id=tmp_path.name, timeline_id="main", branch_id="main", chapter_id=1,
        source_version_id="manual_v001",
    )
    return tmp_path, scope


def _service(root: Path) -> ChapterAssemblyEvidenceService:
    return ChapterAssemblyEvidenceService(get_project_context(root))


def test_generates_version_bound_advisory_evidence_and_preserves_source(tmp_path: Path):
    root, scope = _project(tmp_path)
    source = root / "data" / "manual" / "chapter_001_manual_v001.json"
    chapter = root / "data" / "chapters" / "chapter_001.md"
    before = source.read_bytes()
    chapter_before = chapter.read_bytes()
    result = _service(root).generate(scope)
    assert result["classification"] == "DURABLE_ADVISORY_EVIDENCE"
    assert result["identity"]["source_version_id"] == "manual_v001"
    assert result["identity"]["project_id"] == root.name
    assert result["identity"]["timeline_id"] == "main"
    assert result["identity"]["branch_id"] == "main"
    assert result["identity"]["chapter_id"] == 1
    assert source.read_bytes() == before
    assert chapter.read_bytes() == chapter_before


def test_same_version_replay_is_compatible_and_idempotent(tmp_path: Path):
    root, scope = _project(tmp_path)
    first = _service(root).generate(scope)
    second = _service(root).generate(scope)
    assert first["identity"] == second["identity"]
    assert second["replayed"] is True
    assert len(list((root / "data" / "chapter_assembly_evidence").rglob("*.json"))) == 1


def test_changed_content_is_stale_not_current(tmp_path: Path):
    root, scope = _project(tmp_path)
    service = _service(root)
    service.generate(scope)
    _write_version(root, "第一章已经改变的正文。")
    result = service.read_status(scope)
    assert result["status"] == "STALE"
    assert result["record"]["identity"]["source_fingerprint"] != service._resolve(scope)["source"]["source_fingerprint"]


@pytest.mark.parametrize("field,value,code", [
    ("project_id", "other_project", "PROJECT_SCOPE_MISMATCH"),
    ("timeline_id", "alternate", "TIMELINE_SCOPE_UNSUPPORTED"),
    ("branch_id", "other_branch", "BRANCH_SCOPE_MISMATCH"),
    ("source_version_id", "manual_v999", "SOURCE_VERSION_STALE"),
])
def test_wrong_scope_or_version_fails_closed(tmp_path: Path, field: str, value: str, code: str):
    root, scope = _project(tmp_path)
    values = {**scope.__dict__, field: value}
    with pytest.raises(ChapterAssemblyEvidenceError) as raised:
        _service(root).generate(ChapterAssemblyEvidenceScope(**values))
    assert raised.value.code == code


def test_canon_and_commit_expectations_are_bound_when_present(tmp_path: Path):
    root, scope = _project(tmp_path)
    source_hash = _service(root)._resolve(scope)["source"]["source_fingerprint"]
    commits = root / "data" / "chapter_commits"
    commits.mkdir()
    (commits / "commit_001.json").write_text(json.dumps({
        "commit_id": "commit-001", "chapter_id": 1, "source_hash": source_hash,
    }), encoding="utf-8")
    bound = ChapterAssemblyEvidenceScope(**{**scope.__dict__, "expected_commit_id": "commit-001"})
    assert _service(root).generate(bound)["commit"]["commit_id"] == "commit-001"
    with pytest.raises(ChapterAssemblyEvidenceError) as raised:
        _service(root).generate(ChapterAssemblyEvidenceScope(**{**scope.__dict__, "expected_commit_id": "wrong"}))
    assert raised.value.code == "COMMIT_STALE"


def test_active_canon_is_bound_and_drift_is_not_current(tmp_path: Path):
    root, scope = _project(tmp_path)
    index = root / "data" / "canon_versions" / "chapter_001" / "index.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({
        "versions": [{"canon_version_id": "canon-001", "active": True}],
    }), encoding="utf-8")
    bound = ChapterAssemblyEvidenceScope(**{**scope.__dict__, "expected_canon_revision_id": "canon-001"})
    assert _service(root).generate(bound)["canon"]["canon_revision_id"] == "canon-001"
    index.write_text(json.dumps({
        "versions": [{"canon_version_id": "canon-002", "active": True}],
    }), encoding="utf-8")
    assert _service(root).read_status(bound) == {"status": "INVALID", "code": "CANON_REVISION_STALE"}


def test_compilation_provenance_is_referenced_without_creating_candidate_or_review(tmp_path: Path):
    root, scope = _project(tmp_path)
    path = root / "data" / "manual" / "chapter_001_manual_v001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({
        "candidate_id": "candidate-001", "candidate_fingerprint": "candidate-fingerprint",
        "narrative_compilation": {"candidate_id": "candidate-001", "candidate_fingerprint": "candidate-fingerprint", "scope": {
            "project_id": root.name, "timeline_id": "main", "branch_id": "main", "chapter_id": 1,
            "source_version_id": "manual_v001", "expected_source_fingerprint": "old", "expected_canon_revision_id": "canon-001", "expected_branch_registry_revision": "1",
        }},
    })
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = _service(root).generate(scope)
    assert result["assembly"]["candidate_id"] == "candidate-001"
    assert not (root / "data" / "narrative_candidate_review").exists()


def test_malformed_compilation_provenance_fails_closed(tmp_path: Path):
    root, scope = _project(tmp_path)
    path = root / "data" / "manual" / "chapter_001_manual_v001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidate_scope"] = {"project_id": "other", "timeline_id": "main", "branch_id": "main", "chapter_id": 1, "source_version_id": "manual_v001"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ChapterAssemblyEvidenceError) as raised:
        _service(root).generate(scope)
    assert raised.value.code == "ASSEMBLY_SCOPE_MISMATCH"


def test_branch_registry_drift_makes_previous_evidence_stale(tmp_path: Path):
    root, scope = _project(tmp_path)
    service = _service(root)
    service.generate(scope)
    registry = root / "data" / "branches" / "main" / "registry.json"
    registry.write_text(json.dumps({
        "project_id": root.name, "timeline_id": "main", "active_branch_id": "main", "revision": "2",
    }), encoding="utf-8")
    assert service.read_status(scope)["status"] == "STALE"


def test_corrupt_record_is_invalid_and_never_current(tmp_path: Path):
    root, scope = _project(tmp_path)
    service = _service(root)
    result = service.generate(scope)
    path = service._path(scope, result["identity"]["evidence_id"])
    path.write_text('{"bad": true}', encoding="utf-8")
    assert service.read_status(scope) == {"status": "INVALID", "code": "EVIDENCE_INVALID"}


def test_evidence_does_not_create_review_commit_or_continuity_authority(tmp_path: Path):
    root, scope = _project(tmp_path)
    _service(root).generate(scope)
    data = root / "data"
    assert not (data / "reviews").exists()
    assert not (data / "chapter_commits").exists()
    assert not (data / "narrative_memory" / "continuity").exists()
