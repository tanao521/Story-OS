from __future__ import annotations

import json
from pathlib import Path

from tools.manual_history_recovery import discover_vscode_history, merge_duplicate_candidates, read_expected_hashes, validate_candidate
from tools.data_recovery import sha256


def _expected(path: Path) -> dict[str, str]:
    return {"story_blueprint": sha256(path), "next_chapter_plan": "0" * 64}


def test_reads_full_expected_sha_and_finds_exact_manual_blueprint(tmp_path: Path) -> None:
    hashes = tmp_path / "hashes.json"; hashes.write_text(json.dumps({"story_blueprint": "A" * 64, "next_chapter_plan": "B" * 64}), encoding="utf-8")
    assert read_expected_hashes(hashes)["story_blueprint"] == "A" * 64
    candidate = tmp_path / "manual.json"; candidate.write_text('{"blueprint_version":"1","chapter_plan":[]}', encoding="utf-8")
    row = validate_candidate(candidate, "manual_export", _expected(candidate))
    assert row["target_type"] == "story_blueprint"
    assert row["exact_match"] is True


def test_marks_corrupt_and_wrong_target_candidates(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"; broken.write_text("{broken", encoding="utf-8")
    assert validate_candidate(broken, "manual_export", {"story_blueprint": "0" * 64, "next_chapter_plan": "0" * 64})["json_status"] == "invalid_json"
    plan = tmp_path / "plan.json"; plan.write_text('{"plan_version":"1","chapter_id":2}', encoding="utf-8")
    row = validate_candidate(plan, "manual_export", {"story_blueprint": "0" * 64, "next_chapter_plan": "0" * 64}, expected_hint="story_blueprint")
    assert row["json_status"] == "wrong_target_type"


def test_merges_duplicate_sha_sources(tmp_path: Path) -> None:
    candidate = tmp_path / "blueprint.json"; candidate.write_text('{"blueprint_version":"1","chapter_plan":[]}', encoding="utf-8")
    expected = _expected(candidate)
    first = validate_candidate(candidate, "manual_export", expected)
    second = {**first, "candidate_id": "other", "absolute_source_path": str(tmp_path / "other.json"), "source_category": "vscode_history"}
    merged = merge_duplicate_candidates([first, second])
    assert len(merged) == 1
    assert set(merged[0]["source_categories"]) == {"manual_export", "vscode_history"}


def test_reads_vscode_entries_mapping_only_for_target(tmp_path: Path) -> None:
    target = tmp_path / "data" / "story_blueprint.json"; target.parent.mkdir(); target.write_text("{}", encoding="utf-8")
    history = tmp_path / "history" / "abc"; history.mkdir(parents=True)
    (history / "snapshot").write_text('{"blueprint_version":"1","chapter_plan":[]}', encoding="utf-8")
    (history / "entries.json").write_text(json.dumps({"resource": target.as_uri(), "entries": [{"id": "snapshot"}]}), encoding="utf-8")
    found, summary = discover_vscode_history(history.parent, [target])
    assert found == [history / "snapshot"]
    assert summary["mappings_matched"] == 1
