from __future__ import annotations

import json

from tests.test_phase0d5b_read_model import make_context, seed_branch
from system.simulator_loop_state import SimulatorLoopStateService


def test_recovery_detection_is_read_only(tmp_path):
    context = make_context(tmp_path)
    scope = seed_branch(context)
    operations = context.data_dir / "narrative_turn" / "operations"
    operations.mkdir(parents=True)
    authority = {"operation_id": "turn-op", "operation_type": "confirm", "scope": {"project_id": context.root.name, "timeline_id": "main", "branch_id": scope.branch_id, "chapter_id": 1}}
    (operations / "turn-op.json").write_text(json.dumps(authority), encoding="utf-8")
    (operations / "turn-op.phase.json").write_text(json.dumps({"operation_id": "turn-op", "phase": "result_claimed", **authority["scope"]}), encoding="utf-8")
    before = sorted(p.relative_to(context.data_dir).as_posix() for p in context.data_dir.rglob("*"))
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=scope.branch_id)
    after = sorted(p.relative_to(context.data_dir).as_posix() for p in context.data_dir.rglob("*"))
    assert state.recovery["status"] == "TURN_RECOVERY_REQUIRED"
    assert state.current_stage == "BLOCKED"
    assert before == after
