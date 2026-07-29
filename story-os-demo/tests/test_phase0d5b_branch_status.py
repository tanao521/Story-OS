from __future__ import annotations

from tests.test_phase0d5b_read_model import make_context, seed_branch
from system.simulator_loop_state import SimulatorLoopStateService


def test_branch_readiness_is_projection_only(tmp_path):
    context = make_context(tmp_path)
    scope = seed_branch(context)
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=scope.branch_id)
    assert state.branch["registry_revision"]
    assert state.branch["vector_readiness"] in {"ready", "not_ready", "rebuilding"}
    assert state.branch["blocking_reason"] == "VECTOR_MANIFEST_MISSING"
