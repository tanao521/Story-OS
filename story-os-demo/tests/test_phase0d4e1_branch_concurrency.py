from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.project_context import get_project_context
from core.contracts.narrative_turn import NarrativeTurnError
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def test_competing_create_operations_have_one_winner(tmp_path: Path):
    ctx = get_project_context(tmp_path)

    def create(op_id: str):
        try:
            return BranchLifecycleService(ctx).create(op_id, {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "same"})
        except NarrativeTurnError as exc:
            return {"error": exc.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("op-a", "op-b")))
    assert sum(item.get("branch", {}).get("branch_id") == "same" for item in results) == 1
    assert sum("error" in item for item in results) == 1
    assert len(BranchLifecycleService(ctx).list_branches(ctx.root.name, "main")["branches"]) == 1


def test_different_timelines_can_progress_independently(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    # Seed the second logical timeline through the store, then exercise both
    # lifecycle locks concurrently. Timeline locks must not be global.
    from core.contracts.narrative_turn import TimelineContext
    from system.narrative_branch_store import NarrativeBranchStore
    store = NarrativeBranchStore(ctx)
    store.create_branch(TimelineContext(ctx.root.name, "timeline-b"), "seed", "Seed")

    def create(timeline: str, op_id: str, branch: str):
        return BranchLifecycleService(ctx).create(op_id, {"project_id": ctx.root.name, "timeline_id": timeline, "branch_id": branch})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda x: create(*x), (("main", "main-op", "main"), ("timeline-b", "other-op", "other"))))
    assert {item["branch"]["branch_id"] for item in results} == {"main", "other"}
