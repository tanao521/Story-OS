"""Phase 0D6-A Gate A0: Read-purity hardening tests.

Verifies:
  1. get_selected_version() on missing manifest does NOT create files
  2. get_selected_version() on existing manifest reads correctly
  3. active_canon() on missing canon does NOT create files
  4. active_canon() on existing canon reads correctly
  5. initialize_chapter_versions() is the explicit mutation path
  6. initialize_chapter_canon() is the explicit mutation path
  7. read paths leave filesystem SHA-256 manifest unchanged
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.version_manager import (
    get_selected_version,
    initialize_chapter_versions,
    list_versions,
    save_versions_index,
)
from system.revision_service import RevisionService, CanonVersionNotFoundError


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dir_fingerprint(root: Path) -> dict[str, str]:
    fp: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            fp[str(p.relative_to(root))] = _sha256_file(p)
    return fp


@pytest.fixture
def isolated_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chapters_dir = data_dir / "chapters"
    chapters_dir.mkdir()
    versions_dir = data_dir / "versions"
    versions_dir.mkdir()
    canon_dir = data_dir / "canon_versions"
    canon_dir.mkdir()
    (data_dir / "audit").mkdir()
    (data_dir / "derived_state.json").write_text("{}")
    (data_dir / "state.json").write_text("{}")
    (data_dir / "next_chapter_plan.json").write_text("{}")
    before = _dir_fingerprint(tmp_path)
    yield tmp_path, before


class TestGetSelectedVersionReadPurity:
    def test_missing_manifest_no_write(self, isolated_project):
        tmp_path, before = isolated_project
        data_dir = tmp_path / "data"
        result = get_selected_version(1, data_dir=str(data_dir))
        after = _dir_fingerprint(tmp_path)
        assert result == {}
        assert before == after, f"get_selected_version() wrote files: {set(after) - set(before)}"

    def test_missing_manifest_no_index_created(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        versions_dir = data_dir / "versions"
        assert not list(versions_dir.glob("chapter_001_versions.json"))
        get_selected_version(1, data_dir=str(data_dir))
        assert not list(versions_dir.glob("chapter_001_versions.json")), "index file must not be created by read"

    def test_existing_manifest_read_correctly(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        versions_dir = data_dir / "versions"
        index = {
            "version_index": "1.5",
            "chapter_id": 1,
            "drafts": [],
            "edited": [],
            "manual": [
                {
                    "source_type": "manual",
                    "version": 1,
                    "version_label": "manual_v001",
                    "json_path": str(data_dir / "manual" / "chapter_001_manual_v001.json"),
                    "markdown_path": str(data_dir / "manual" / "chapter_001_manual_v001.md"),
                    "chapter_id": 1,
                    "preview": "test",
                }
            ],
            "selected": {},
        }
        versions_dir.mkdir(parents=True, exist_ok=True)
        (versions_dir / "chapter_001_versions.json").write_text(json.dumps(index, ensure_ascii=False))
        manual_dir = data_dir / "manual"
        manual_dir.mkdir(parents=True, exist_ok=True)
        (manual_dir / "chapter_001_manual_v001.json").write_text(json.dumps({"manual_text": "hello"}, ensure_ascii=False))
        result = get_selected_version(1, data_dir=str(data_dir))
        assert result.get("version_label") == "manual_v001"

    def test_list_versions_remains_pure(self, isolated_project):
        tmp_path, before = isolated_project
        data_dir = tmp_path / "data"
        result = list_versions(1, data_dir=str(data_dir))
        after = _dir_fingerprint(tmp_path)
        assert before == after, "list_versions must be pure read"


class TestInitializeVersions:
    def test_explicit_create_creates_index(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        versions_dir = data_dir / "versions"
        assert not list(versions_dir.glob("chapter_001_versions.json"))
        initialize_chapter_versions(1, data_dir=str(data_dir))
        assert list(versions_dir.glob("chapter_001_versions.json")), "initialize must create index"

    def test_idempotent_replay(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        initialize_chapter_versions(1, data_dir=str(data_dir))
        first = _dir_fingerprint(tmp_path)
        initialize_chapter_versions(1, data_dir=str(data_dir))
        second = _dir_fingerprint(tmp_path)
        assert first == second, "second init must be idempotent"


class TestActiveCanonReadPurity:
    def test_missing_canon_no_write(self, isolated_project):
        tmp_path, before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        with pytest.raises(CanonVersionNotFoundError):
            svc.active_canon(1)
        after = _dir_fingerprint(tmp_path)
        assert before == after, f"active_canon() wrote files: {set(after) - set(before)}"

    def test_missing_canon_no_files_created(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        canon_dir = data_dir / "canon_versions" / "chapter_001"
        assert not canon_dir.exists()
        with pytest.raises(CanonVersionNotFoundError):
            svc.active_canon(1)
        assert not canon_dir.exists(), "canon files must not be created by read"

    def test_existing_canon_reads_correctly(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        canon_dir = data_dir / "canon_versions" / "chapter_001"
        canon_dir.mkdir(parents=True, exist_ok=True)
        content_path = canon_dir / "canon_v001.md"
        content_path.write_text("test canon content")
        index = {
            "schema_version": "1.0",
            "chapter_id": 1,
            "current_version_id": "canon-chapter-001-v001",
            "versions": [
                {
                    "canon_version_id": "canon-chapter-001-v001",
                    "chapter_id": 1,
                    "version_number": 1,
                    "content_path": str(content_path),
                    "content_hash": hashlib.sha256(b"test canon content").hexdigest(),
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "activated_at": "2026-01-01T00:00:00+00:00",
                    "active": True,
                    "source": "commit",
                    "word_count": 4,
                }
            ],
        }
        (canon_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False))
        result = svc.active_canon(1)
        assert result["canon_version_id"] == "canon-chapter-001-v001"
        assert result["content"] == "test canon content"

    def test_read_active_canon_returns_none_when_missing(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        result = svc.read_active_canon(1)
        assert result is None


class TestInitializeCanon:
    def test_explicit_create_creates_canon(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        canon_dir = data_dir / "canon_versions" / "chapter_001"
        assert not canon_dir.exists()
        result = svc.initialize_chapter_canon(1, "initial content")
        assert result is not None
        assert canon_dir.exists()

    def test_idempotent_replay(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        context = get_project_context(tmp_path)
        svc = RevisionService(context)
        result1 = svc.initialize_chapter_canon(1, "initial content")
        canon_id_1 = result1.get("canon_version_id") or result1.get("revision_id")
        result2 = svc.initialize_chapter_canon(1, "initial content")
        canon_id_2 = result2.get("canon_version_id") or result2.get("revision_id")
        assert canon_id_1 == canon_id_2, "second init must be idempotent"


class TestSimulatorLoopStateKeyError:
    def test_build_with_missing_manifest_does_not_crash(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        chapters_dir = data_dir / "chapters"
        chapter_file = chapters_dir / "chapter_001.md"
        chapter_file.write_text("test chapter")
        context = get_project_context(tmp_path)
        from system.narrative_branch_lifecycle_service import BranchLifecycleService
        bls = BranchLifecycleService(context)
        bls.create(
            operation_id="op-test-branch",
            values={"project_id": tmp_path.name, "timeline_id": "main", "branch_id": "main", "display_name": "Main"},
        )
        from system.simulator_loop_state import SimulatorLoopStateService
        svc = SimulatorLoopStateService(context)
        try:
            state = svc.build(project_id=tmp_path.name, timeline_id="main", chapter_id=1, branch_id="main")
            assert state is not None
        except KeyError as exc:
            pytest.fail(f"build() raised KeyError: {exc}")

    def test_build_with_empty_branch_list_handled(self, isolated_project):
        tmp_path, _before = isolated_project
        data_dir = tmp_path / "data"
        chapters_dir = data_dir / "chapters"
        chapter_file = chapters_dir / "chapter_001.md"
        chapter_file.write_text("test chapter")
        context = get_project_context(tmp_path)
        from system.simulator_loop_state import SimulatorLoopStateService, SimulatorLoopStateError
        svc = SimulatorLoopStateService(context)
        try:
            state = svc.build(project_id=tmp_path.name, timeline_id="main", chapter_id=1, branch_id="main")
            assert state is not None
        except SimulatorLoopStateError:
            pass
        except KeyError as exc:
            pytest.fail(f"build() raised KeyError on empty branches: {exc}")