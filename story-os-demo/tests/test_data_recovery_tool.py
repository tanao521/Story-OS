from __future__ import annotations

from pathlib import Path

import tools.data_recovery as recovery
from tools.data_recovery import inventory, sha256, structural_diff, write_evidence


def test_inventory_finds_exact_hash_without_writing_candidate(tmp_path: Path, monkeypatch) -> None:
    # ``tmp_path`` itself is deliberately under a pytest directory.  Disable
    # that one path filter only for this fixture so the exact-hash behavior is
    # tested independently from the production scan exclusion below.
    monkeypatch.setattr(recovery, "_allowed", lambda path, excluded_roots: True)
    source = tmp_path / "source"; source.mkdir()
    blueprint = source / "story_blueprint.backup.json"; blueprint.write_text('{"blueprint_version":"1","title":"original"}', encoding="utf-8")
    expected = {"story_blueprint": sha256(blueprint), "next_chapter_plan": "missing"}
    before = sha256(blueprint)
    rows = inventory([source], expected)
    artifact = tmp_path / "evidence"; write_evidence(rows, artifact, expected)
    assert rows[0]["matches_expected_pretest_sha"] is True
    assert sha256(blueprint) == before
    assert sha256(next((artifact / "exact_matches").iterdir())) == before


def test_inventory_never_promotes_near_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "_allowed", lambda path, excluded_roots: True)
    source = tmp_path / "source"; source.mkdir()
    path = source / "next_chapter_plan.old.json"; path.write_text('{"plan_version":"1","chapter_id":7}', encoding="utf-8")
    rows = inventory([source], {"story_blueprint": "", "next_chapter_plan": "0" * 64})
    assert rows[0]["matches_expected_pretest_sha"] is False


def test_inventory_excludes_pytest_temporary_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"; source.mkdir()
    (source / "story_blueprint.json").write_text('{"title":"excluded"}', encoding="utf-8")
    assert inventory([source], {"story_blueprint": "", "next_chapter_plan": ""}) == []


def test_pytest_temporary_path_filter_is_narrow() -> None:
    assert recovery._is_pytest_temporary_path(Path("D:/repo/.pytest-tmp-phase-16/test/story_blueprint.json"))
    assert recovery._is_pytest_temporary_path(Path("D:/temp/pytest-of-user/pytest-12/test_case0/story_blueprint.json"))
    assert recovery._is_pytest_temporary_path(Path("D:/temp/storyos-pytest-phase-16-4bv-full-1/test/story_blueprint.json"))
    assert recovery._is_pytest_temporary_path(Path("D:/temp/storyos-phase-16-4bv-r1-1/pytest-temp/test/story_blueprint.json"))
    assert not recovery._is_pytest_temporary_path(Path("D:/projects/pytest-novel-project/data/story_blueprint.json"))
    assert not recovery._is_pytest_temporary_path(Path("D:/stories/temporary-kingdom/data/story_blueprint.json"))


def test_inventory_rejects_invalid_json_even_when_hash_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "_allowed", lambda path, excluded_roots: True)
    source = tmp_path / "source"; source.mkdir()
    candidate = source / "story_blueprint.json"; candidate.write_text('{not json', encoding="utf-8")
    rows = inventory([source], {"story_blueprint": sha256(candidate), "next_chapter_plan": ""})
    assert rows[0]["json_valid"] is False
    assert rows[0]["matches_expected_pretest_sha"] is False


def test_inventory_rejects_wrong_target_schema_even_when_hash_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "_allowed", lambda path, excluded_roots: True)
    source = tmp_path / "source"; source.mkdir()
    candidate = source / "story_blueprint.json"; candidate.write_text('{"plan_version":"1"}', encoding="utf-8")
    rows = inventory([source], {"story_blueprint": sha256(candidate), "next_chapter_plan": ""})
    assert rows[0]["json_valid"] is True
    assert rows[0]["target_schema_valid"] is False
    assert rows[0]["matches_expected_pretest_sha"] is False


def test_structural_diff_reports_fields_without_source_mutation(tmp_path: Path) -> None:
    current = tmp_path / "current.json"; candidate = tmp_path / "candidate.json"
    current.write_text('{"chapter_id":7,"scene_plan":[{"scene_id":"s-1"}]}', encoding="utf-8")
    candidate.write_text('{"chapter_id":6,"legacy":true}', encoding="utf-8")
    before = sha256(candidate)
    report = structural_diff(current, candidate)
    assert report["top_level_only_in_current"] == ["scene_plan"]
    assert report["top_level_only_in_candidate"] == ["legacy"]
    assert "chapter_id" in report["changed_top_level_fields"]
    assert sha256(candidate) == before
