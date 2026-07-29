from __future__ import annotations

import json
from pathlib import Path

from core.project_context import get_project_context
from core.contracts.narrative_turn import NarrativeTurnError
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def test_operation_authority_and_expected_paths(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    result = service.create("op-create", {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "root"})
    assert result["registry_revision"]
    ops = ctx.data_dir / "branch_operations"
    authority = ops / "op-create.json"
    phase = ops / "op-create.phase.json"
    assert authority.exists() and phase.exists()
    payload = json.loads(authority.read_text(encoding="utf-8"))
    assert payload["operation_id"] == "op-create"
    assert payload["canonical_request_fingerprint"]
    assert "root" not in payload.get("raw_text", "")
    assert "phase" not in payload
    before = authority.read_text(encoding="utf-8")
    service.create("op-create", {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "root"})
    assert authority.read_text(encoding="utf-8") == before
    assert not (ctx.data_dir / "narrative_memory" / "events").exists()
    assert not (ctx.data_dir / "chroma").exists()


def test_repeated_archive_and_restore_do_not_duplicate_lifecycle_events(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    service.create("create-a", {**scope, "branch_id": "a"})
    service.create("create-b", {**scope, "branch_id": "b"})
    revision = service.list_branches(**scope)["registry_revision"]
    service.select("select-a", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    service.archive("archive-a", {**scope, "branch_id": "a", "replacement_branch_id": "b", "expected_registry_revision": revision})
    replay = service.archive("archive-a", {**scope, "branch_id": "a", "replacement_branch_id": "b", "expected_registry_revision": revision})
    assert replay["idempotent_replay"] is True
    store = service.store
    timeline = service._timeline("main")
    assert len(store.get_lifecycle_events(timeline, "a")) == 1
    revision = service.list_branches(**scope)["registry_revision"]
    service.restore("restore-a", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    service.restore("restore-a", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    assert len(store.get_lifecycle_events(timeline, "a")) == 2


def test_phase_scope_mismatch_fails_closed(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "root"}
    service.create("scope-op", scope)
    phase = ctx.data_dir / "branch_operations" / "scope-op.phase.json"
    data = json.loads(phase.read_text(encoding="utf-8"))
    data["timeline_id"] = "other"
    phase.write_text(json.dumps(data), encoding="utf-8")
    try:
        service.create("scope-op", scope)
    except Exception as exc:
        assert getattr(exc, "code", "") == "NARRATIVE_TURN_OPERATION_COLLISION"
    else:
        raise AssertionError("phase scope mismatch must fail closed")


def test_phase_request_fingerprint_mismatch_fails_closed(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "root"}
    service.create("fingerprint-op", scope)
    phase = ctx.data_dir / "branch_operations" / "fingerprint-op.phase.json"
    data = json.loads(phase.read_text(encoding="utf-8"))
    data["canonical_request_fingerprint"] = "0" * 64
    phase.write_text(json.dumps(data), encoding="utf-8")
    try:
        service.create("fingerprint-op", scope)
    except NarrativeTurnError as exc:
        assert exc.code == NarrativeTurnError.OPERATION_COLLISION
    else:
        raise AssertionError("phase fingerprint mismatch must fail closed")
