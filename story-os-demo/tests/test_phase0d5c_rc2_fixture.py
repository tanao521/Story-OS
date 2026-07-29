"""Authoritative ready fixture checks for Phase 0D5-C-RC2."""
from __future__ import annotations

import tempfile
from pathlib import Path

from core.contracts.narrative_turn import NarrativeScope
from core.project_context import get_project_context
from system.narrative_turn_context import NarrativeTurnContextBinder
from system.simulator_loop_state import SimulatorLoopStateService
from tests._rc2_browser_fixture_server import setup_workspace


def test_fixture_has_ready_scope_and_branch_isolation():
    root = Path(tempfile.mkdtemp())
    info = setup_workspace(root)
    context = get_project_context(root / "projects" / info["project_id"])
    model = SimulatorLoopStateService(context).build(
        project_id=info["project_id"], timeline_id="tl-main", branch_id="root", chapter_id=1
    ).to_dict()
    assert model["scope"]["source_version_id"] == "manual_v001"
    assert model["scope"]["canon_revision_id"] == "canon_rc2_c1"
    assert model["branch"]["readiness"] == "ready"
    snapshot = NarrativeTurnContextBinder(context).bind(NarrativeScope(info["project_id"], "tl-main", "root"), 1)
    assert snapshot.source_version_id == "manual_v001"
    assert snapshot.canon_revision == "canon_rc2_c1"
    assert model["candidate"]["can_compile"] is True
    assert model["turn"]["history_summary"]["count"] == 2
