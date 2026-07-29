from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.branch_narrative_memory_service import BranchMemoryArchived, BranchMemoryService


def _branch(tmp_path: Path):
    context = get_project_context(tmp_path)
    service = BranchLifecycleService(context)
    scope = {"project_id": context.root.name, "timeline_id": "main"}
    service.create("seed-a", {**scope, "branch_id": "a"})
    service.create("seed-b", {**scope, "branch_id": "b"})
    return context, scope, BranchMemoryService(context)


def test_branch_memory_paths_and_scope_are_explicit(tmp_path: Path):
    context, scope, memory = _branch(tmp_path)
    timeline = memory.scope(**scope, branch_id="a")
    event = memory.append_event(timeline, "a", {"chapter_id": 1, "event_type": "arrival", "payload": {"branch": "a"}})
    assert event["project_id"] == context.root.name and event["branch_id"] == "a"
    assert (context.data_dir / "narrative_memory" / "events" / "main" / "a" / "chapter_001.json").exists()
    assert not (context.data_dir / "narrative_memory" / "events" / "main" / "b" / "chapter_001.json").exists()
    with pytest.raises(Exception):
        memory.scope(context.root.name, "main", "missing")


def test_archived_branch_rejects_memory_mutation(tmp_path: Path):
    context, scope, memory = _branch(tmp_path)
    branch_service = BranchLifecycleService(context)
    revision = branch_service.list_branches(**scope)["registry_revision"]
    branch_service.select("select-a", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = branch_service.list_branches(**scope)["registry_revision"]
    branch_service.archive("archive-a", {**scope, "branch_id": "a", "replacement_branch_id": "b", "expected_registry_revision": revision})
    timeline = memory.scope(**scope, branch_id="a")
    with pytest.raises(BranchMemoryArchived):
        memory.append_event(timeline, "a", {"chapter_id": 1, "event_type": "blocked"})


def test_authority_state_path_is_read_only_for_e2(tmp_path: Path):
    context, scope, memory = _branch(tmp_path)
    timeline = memory.scope(**scope, branch_id="a")
    state = memory.project_state(timeline, "a")
    state_path = context.data_dir / "narrative_memory" / "state" / "main" / "a" / "current.json"
    assert not state_path.exists() and state == {}
    assert len(list((context.data_dir / "narrative_memory" / "state").glob("current.json"))) == 0
