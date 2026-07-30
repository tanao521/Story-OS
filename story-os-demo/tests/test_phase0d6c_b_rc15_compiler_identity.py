from __future__ import annotations

from pathlib import Path

import pytest

from core.contracts.narrative_turn import TimelineContext
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_chapter_compiler import CompilationScope, NarrativeChapterCompiler
from system.project_identity_resolver import ProjectIdentityResolver


def _scope(project_id: str, registry_revision: str) -> CompilationScope:
    return CompilationScope(
        project_id=project_id,
        timeline_id="main",
        branch_id="main",
        chapter_id=2,
        source_version_id="draft_v001",
        expected_source_fingerprint="a" * 64,
        expected_canon_revision_id="canon-chapter-002-v001",
        expected_branch_registry_revision=registry_revision,
    )


def test_compiler_keeps_canonical_authority_and_uses_storage_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._phase0d6c_fv_browser_fixture_server import setup_workspace

    monkeypatch.chdir(tmp_path)
    info = setup_workspace(tmp_path)
    identity = ProjectIdentityResolver(tmp_path).resolve(info["project_id"])
    registry_revision = NarrativeBranchStore(identity.context).get_registry_revision(
        TimelineContext(identity.storage_project_id, "main")
    )
    scope = _scope(identity.project_id, registry_revision)
    compiler = NarrativeChapterCompiler(
        identity.context, canonical_project_id=identity.project_id
    )

    scope.validate(identity.context, identity.project_id)
    assert compiler._storage_scope(scope).project_id == identity.storage_project_id
    assert scope.project_id == identity.project_id
    compiler._branch_check(scope)


def test_compiler_rejects_cross_project_canonical_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._phase0d6c_fv_browser_fixture_server import setup_workspace
    from system.narrative_chapter_compiler import NarrativeCompilationError

    monkeypatch.chdir(tmp_path)
    info = setup_workspace(tmp_path)
    identity = ProjectIdentityResolver(tmp_path).resolve(info["project_id"])
    scope = _scope(info["project_b"]["project_id"], "irrelevant")

    with pytest.raises(NarrativeCompilationError) as caught:
        scope.validate(identity.context, identity.project_id)
    assert caught.value.code == "COMPILATION_SCOPE_REQUIRED"
