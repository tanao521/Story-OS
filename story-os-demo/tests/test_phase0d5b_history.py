from __future__ import annotations

from tests.test_phase0d5b_read_model import make_context, seed_branch, seed_turn
from system.simulator_loop_state import SimulatorLoopStateService


def test_history_is_scoped_to_branch(tmp_path):
    context = make_context(tmp_path)
    scope = seed_branch(context, "root")
    seed_turn(context, scope, "root-turn")
    other = seed_branch(context, "other")
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=other.branch_id)
    assert state.turn["history"] == []
    assert state.scope["branch_id"] == "other"
