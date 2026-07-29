from __future__ import annotations

import json
import hashlib

from tests.test_phase0d5b_read_model import make_context, seed_branch
from system.simulator_loop_state import SimulatorLoopStateService


def test_candidate_summary_is_scoped_and_approval_gap_is_explicit(tmp_path):
    context = make_context(tmp_path)
    scope = seed_branch(context)
    manual = context.manual_dir
    manual.mkdir(parents=True)
    source_fp = hashlib.sha256(b"candidate").hexdigest()
    payload = {
        "chapter_id": 1, "version_label": "manual_v001", "manual_text": "candidate", "created_at": "now",
        "candidate_id": "candidate-1", "candidate_fingerprint": "f" * 64, "candidate_scope": {"project_id": context.root.name, "timeline_id": "main", "branch_id": scope.branch_id, "chapter_id": 1, "source_version_id": "manual_v001", "expected_canon_revision_id": "canon-1", "expected_branch_registry_revision": "1"},
        "source_version_id": "manual_v001", "source_fingerprint": source_fp, "canon_revision_id": "canon-1", "review_status": "pending", "narrative_compilation": {"candidate_id": "candidate-1", "candidate_fingerprint": "f" * 64, "review_status": "pending", "scope": {"project_id": context.root.name, "timeline_id": "main", "branch_id": scope.branch_id, "chapter_id": 1, "source_version_id": "manual_v001", "expected_canon_revision_id": "canon-1", "expected_branch_registry_revision": "1"}},
    }
    (manual / "chapter_001_manual_v001.json").write_text(json.dumps(payload), encoding="utf-8")
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=scope.branch_id, source_version_id="manual_v001")
    assert state.candidate["candidate_list"][0]["candidate_id"] == "candidate-1"
    assert state.candidate["candidate_list"][0]["review_status"] == "pending"
    assert state.candidate["approval_status"] == "pending"
    assert state.approval["can_approve"] is True
