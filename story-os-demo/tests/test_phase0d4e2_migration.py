from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.branch_narrative_memory_service import MigrationError, NarrativeMemoryMigrationService


def test_migration_dry_run_is_zero_write_and_execute_is_copy_only(tmp_path: Path):
    context = get_project_context(tmp_path)
    branch = BranchLifecycleService(context)
    project_id = context.root.name
    branch.create("seed", {"project_id": project_id, "timeline_id": "main", "branch_id": "a"})
    source = context.data_dir / "narrative_memory" / "events" / "chapter_001.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([{"summary": "legacy"}]), encoding="utf-8")
    before = source.read_bytes()
    service = NarrativeMemoryMigrationService(context)
    plan = service.plan(operation_id="mig-1", project_id=project_id, timeline_id="main", target_branch_id="a", legacy_scope_acknowledged=True)
    assert not (context.data_dir / "narrative_memory" / "migrations").exists()
    result = service.execute(plan, operation_id="mig-1", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])
    assert result["idempotent_replay"] is False
    assert source.read_bytes() == before
    target = context.data_dir / "narrative_memory" / "events" / "main" / "a" / "chapter_001.json"
    migrated = json.loads(target.read_text(encoding="utf-8"))[0]
    assert migrated["branch_id"] == "a" and migrated["migration_provenance"]["source_kind"] == "legacy_unscoped"
    assert service.execute(plan, operation_id="mig-1", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])["idempotent_replay"] is True


def test_migration_source_change_fails_closed(tmp_path: Path):
    context = get_project_context(tmp_path)
    branch = BranchLifecycleService(context)
    pid = context.root.name
    branch.create("seed", {"project_id": pid, "timeline_id": "main", "branch_id": "a"})
    source = context.data_dir / "narrative_memory" / "events" / "chapter_001.json"
    source.parent.mkdir(parents=True)
    source.write_text("[]", encoding="utf-8")
    service = NarrativeMemoryMigrationService(context)
    plan = service.plan(operation_id="mig-2", project_id=pid, timeline_id="main", target_branch_id="a", legacy_scope_acknowledged=True)
    source.write_text("[1]", encoding="utf-8")
    with pytest.raises(MigrationError):
        service.execute(plan, operation_id="mig-2", dry_run_plan_fingerprint=plan["dry_run_plan_fingerprint"])
