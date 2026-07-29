from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.branch_narrative_memory_service import BranchMemoryService


def test_same_branch_event_mutations_are_serialized(tmp_path: Path):
    context = get_project_context(tmp_path)
    lifecycle = BranchLifecycleService(context)
    pid = context.root.name
    lifecycle.create("seed", {"project_id": pid, "timeline_id": "main", "branch_id": "a"})

    def append(index: int):
        memory = BranchMemoryService(get_project_context(tmp_path))
        scope = memory.scope(pid, "main", "a")
        return memory.append_event(scope, "a", {"chapter_id": 1, "event_id": f"event-{index}", "event_type": "fact", "payload": {"index": index}})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(8)))
    memory = BranchMemoryService(context)
    scope = memory.scope(pid, "main", "a")
    events = memory.events(scope, "a")
    assert len(events) == 8 and {event["payload"]["index"] for event in events} == set(range(8))
