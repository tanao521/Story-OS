from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.apply_user_approved_baseline import apply_user_approved_baseline
from tools.data_recovery import sha256


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _prepared_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"; data = project / "data"; data.mkdir(parents=True)
    _write_json(data / "story_blueprint.json", {"blueprint_version": "old", "chapter_plan": []})
    _write_json(data / "next_chapter_plan.json", {"plan_version": "old", "chapter_id": 7})
    _write_json(data / "state.json", {"current_chapter": 6})
    artifact = tmp_path / "recovery"; candidates = artifact / "candidates"; candidates.mkdir(parents=True)
    blueprint = candidates / "blue-01-blueprint.json"; _write_json(blueprint, {"blueprint_version": "new", "chapter_plan": [{"chapter_id": 7}]})
    plan = candidates / "plan-02-plan.json"; _write_json(plan, {"plan_version": "new", "chapter_id": 7})
    _write_json(artifact / "inventory.json", [
        {"candidate_id": "blue-01", "target_type": "story_blueprint", "json_status": "valid_json", "sha256": sha256(blueprint)},
        {"candidate_id": "plan-02", "target_type": "next_chapter_plan", "json_status": "valid_json", "sha256": sha256(plan)},
    ])
    return project, artifact


def test_apply_approved_baseline_uses_evidence_and_preserves_state(tmp_path: Path) -> None:
    project, artifact = _prepared_project(tmp_path)
    state_before = sha256(project / "data/state.json")
    audit = apply_user_approved_baseline(project_root=project, recovery_artifact=artifact, incident_dir=tmp_path / "incident", story_blueprint_candidate_id="blue-01", next_chapter_plan_candidate_id="plan-02")
    assert audit["baseline_type"] == "user_approved_new_baseline"
    assert audit["original_version_recovered"] is False
    assert sha256(project / "data/state.json") == state_before
    assert json.loads((project / "data/next_chapter_plan.json").read_text(encoding="utf-8"))["chapter_id"] == 7
    assert (tmp_path / "incident/pre-user-approved-baseline-story_blueprint.json").is_file()


def test_apply_rejects_unknown_candidate_without_writing(tmp_path: Path) -> None:
    project, artifact = _prepared_project(tmp_path)
    before = sha256(project / "data/story_blueprint.json")
    with pytest.raises(ValueError, match="INVALID_APPROVED_CANDIDATE"):
        apply_user_approved_baseline(project_root=project, recovery_artifact=artifact, incident_dir=tmp_path / "incident", story_blueprint_candidate_id="missing", next_chapter_plan_candidate_id="plan-02")
    assert sha256(project / "data/story_blueprint.json") == before
