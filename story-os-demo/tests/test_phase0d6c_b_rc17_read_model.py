from __future__ import annotations

from pathlib import Path

from system.project_identity_resolver import ProjectIdentityResolver
from system.simulator_loop_state import SimulatorLoopStateService


def test_candidate_authorities_are_enumerated_with_canonical_project_scope(
    tmp_path: Path, monkeypatch,
) -> None:
    from tests._phase0d6c_fv_browser_fixture_server import setup_workspace

    monkeypatch.chdir(tmp_path)
    info = setup_workspace(tmp_path)
    identity = ProjectIdentityResolver(tmp_path).resolve(info["project_id"])
    service = SimulatorLoopStateService(
        identity.context, canonical_project_id=identity.project_id
    )
    observed: dict[str, str] = {}
    original_candidates = service._candidates
    original_recovery = service._recovery
    original_commit = service._commit

    def capture_candidates(scope, chapter_id, current_canon, source_fp):
        observed["candidate"] = scope["project_id"]
        return original_candidates(scope, chapter_id, current_canon, source_fp)

    def capture_recovery(scope):
        observed["recovery"] = scope["project_id"]
        return original_recovery(scope)

    def capture_commit(scope):
        observed["commit"] = scope["project_id"]
        return original_commit(scope)

    monkeypatch.setattr(service, "_candidates", capture_candidates)
    monkeypatch.setattr(service, "_recovery", capture_recovery)
    monkeypatch.setattr(service, "_commit", capture_commit)
    model = service.build(
        project_id=identity.project_id,
        timeline_id="main",
        branch_id="main",
        chapter_id=2,
        source_version_id="draft_v001",
    )

    assert observed == {
        "candidate": identity.project_id,
        "recovery": identity.project_id,
        "commit": identity.project_id,
    }
    assert identity.project_id != identity.storage_project_id
    assert model.scope["project_id"] == identity.project_id
