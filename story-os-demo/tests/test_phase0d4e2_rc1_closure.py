from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.project_context import bind_project_context, get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.branch_narrative_memory_service import NarrativeMemoryMigrationService
from web.app import app


def _setup(tmp_path: Path):
    context = get_project_context(tmp_path)
    BranchLifecycleService(context).create("seed", {"project_id": context.root.name, "timeline_id": "main", "branch_id": "a"})
    source = context.data_dir / "narrative_memory" / "events" / "chapter_001.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([{"summary": "LEGACY_SENTINEL"}]), encoding="utf-8")
    return context, source


def test_legacy_mutations_are_disabled_and_reads_marked(tmp_path: Path):
    context, _ = _setup(tmp_path)
    with bind_project_context(context):
        client = TestClient(app)
        assert client.post("/api/narrative-memory/chapters/1/extract").status_code == 410
        assert client.post("/api/narrative-memory/project").status_code == 410
        assert client.post("/api/narrative-memory/overrides/pins", json={"value": "x"}).status_code == 410
        legacy = client.get("/api/narrative-memory/events").json()["result"]
        assert legacy["legacy_unscoped"] is True and legacy["mutation_allowed"] is False


@pytest.mark.parametrize("fault", ["after_immutable_authority_claim", "after_first_target_copy", "after_all_target_copies", "after_migration_manifest_publication", "before_completed_marker"])
def test_migration_fault_recovery_keeps_authority_and_source(fault: str, tmp_path: Path):
    context, source = _setup(tmp_path)
    service = NarrativeMemoryMigrationService(context)
    plan = service.plan(operation_id="recover", project_id=context.root.name, timeline_id="main", target_branch_id="a", legacy_scope_acknowledged=True)
    source_bytes = source.read_bytes()
    def inject(point):
        if point == fault: raise RuntimeError(point)
    with pytest.raises(RuntimeError):
        NarrativeMemoryMigrationService(context, fault_injector=inject).execute(plan, operation_id="recover", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])
    authority = context.data_dir / "narrative_memory" / "migrations" / "recover.json"
    authority_bytes = authority.read_bytes()
    result = NarrativeMemoryMigrationService(context).execute(plan, operation_id="recover", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])
    assert source.read_bytes() == source_bytes and authority.read_bytes() == authority_bytes
    assert result["idempotent_replay"] is False
    assert NarrativeMemoryMigrationService(context).execute(plan, operation_id="recover", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])["idempotent_replay"] is True
