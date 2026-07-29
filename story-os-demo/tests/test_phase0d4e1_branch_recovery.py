from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def test_same_operation_recovers_from_missing_phase_marker(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "recover"}
    service.create("recover-op", scope)
    phase = ctx.data_dir / "branch_operations" / "recover-op.phase.json"
    phase.unlink()
    replay = BranchLifecycleService(ctx).create("recover-op", scope)
    assert replay["recovery_performed"] is True
    replay = BranchLifecycleService(ctx).create("recover-op", scope)
    assert replay["idempotent_replay"] is True
    assert ctx.data_dir.joinpath("branches", "main", "branches", "recover.json").exists()
    authority = json.loads((ctx.data_dir / "branch_operations" / "recover-op.json").read_text(encoding="utf-8"))
    phase_data = json.loads((ctx.data_dir / "branch_operations" / "recover-op.phase.json").read_text(encoding="utf-8"))
    assert "phase" not in authority
    assert phase_data["phase"] == "completed"


@pytest.mark.parametrize("operation", ["select", "archive", "restore"])
def test_missing_phase_reconstructed_from_durable_artifacts(operation: str, tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    service.create("seed-a", {**scope, "branch_id": "a"})
    service.create("seed-b", {**scope, "branch_id": "b"})
    revision = service.list_branches(**scope)["registry_revision"]
    if operation == "select":
        values = {**scope, "branch_id": "a", "expected_registry_revision": revision}
    elif operation == "archive":
        service.select("seed-select", {**scope, "branch_id": "a", "expected_registry_revision": revision})
        revision = service.list_branches(**scope)["registry_revision"]
        values = {**scope, "branch_id": "a", "replacement_branch_id": "b", "expected_registry_revision": revision}
    else:
        service.select("seed-select", {**scope, "branch_id": "a", "expected_registry_revision": revision})
        revision = service.list_branches(**scope)["registry_revision"]
        service.archive("seed-archive", {**scope, "branch_id": "b", "expected_registry_revision": revision})
        revision = service.list_branches(**scope)["registry_revision"]
        values = {**scope, "branch_id": "b", "expected_registry_revision": revision}
    operation_id = f"missing-phase-{operation}"
    first = getattr(service, operation)(operation_id, values)
    authority_path = ctx.data_dir / "branch_operations" / f"{operation_id}.json"
    authority_bytes = authority_path.read_bytes()
    (ctx.data_dir / "branch_operations" / f"{operation_id}.phase.json").unlink()
    recovered = getattr(BranchLifecycleService(ctx), operation)(operation_id, values)
    assert recovered["recovery_performed"] is True
    assert authority_path.read_bytes() == authority_bytes
    replay = getattr(BranchLifecycleService(ctx), operation)(operation_id, values)
    assert replay["idempotent_replay"] is True


@pytest.mark.parametrize("operation, fault_point, expect_recovery", [
    ("create", "after_operation_claim", False),
    ("create", "after_identity_publish", True),
    ("create", "before_completed_marker", True),
    ("select", "after_operation_claim", False),
    ("select", "after_registry_publish", True),
    ("select", "before_completed_marker", True),
    ("archive", "after_operation_claim", False),
    ("archive", "after_archive", True),
    ("archive", "before_completed_marker", True),
    ("restore", "after_operation_claim", False),
    ("restore", "after_restore", True),
    ("restore", "before_completed_marker", True),
])
def test_fault_matrix_recovers(operation: str, fault_point: str, expect_recovery: bool, tmp_path: Path):
    ctx = get_project_context(tmp_path)
    clean = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    clean.create("seed-a", {**scope, "branch_id": "a"})
    clean.create("seed-b", {**scope, "branch_id": "b"})
    revision = clean.list_branches(**scope)["registry_revision"]
    clean.select("seed-select", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = clean.list_branches(**scope)["registry_revision"]
    if operation == "create":
        values = {**scope, "branch_id": "faulted"}
    elif operation == "select":
        values = {**scope, "branch_id": "b", "expected_registry_revision": revision}
    elif operation == "archive":
        values = {**scope, "branch_id": "a", "replacement_branch_id": "b", "expected_registry_revision": revision}
    else:
        clean.archive("seed-archive", {**scope, "branch_id": "b", "expected_registry_revision": revision})
        revision = clean.list_branches(**scope)["registry_revision"]
        values = {**scope, "branch_id": "b", "expected_registry_revision": revision}

    def inject(point: str):
        if point == fault_point:
            raise RuntimeError(point)

    with pytest.raises(RuntimeError, match=fault_point):
        getattr(BranchLifecycleService(ctx, fault_injector=inject), operation)(f"fault-{operation}", values)
    recovered = getattr(BranchLifecycleService(ctx), operation)(f"fault-{operation}", values)
    assert recovered["recovery_performed"] is expect_recovery
    replay = getattr(BranchLifecycleService(ctx), operation)(f"fault-{operation}", values)
    assert replay["idempotent_replay"] is True
