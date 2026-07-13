import json
from pathlib import Path
from typing import Any

from web import routes


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_version(root: Path, kind: str, version: int, field: str, text: str) -> None:
    stem = f"chapter_001_{kind}_v{version:03d}"
    _write_json(
        root / "data" / ("drafts" if kind == "draft" else kind) / f"{stem}.json",
        {"chapter_id": 1, "version": version, "version_label": f"{kind}_v{version:03d}", field: text},
    )
    (root / "data" / ("drafts" if kind == "draft" else kind) / f"{stem}.md").write_text(text, encoding="utf-8")


def test_approve_archives_non_committed_versions(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_json(tmp_path / "data" / "state.json", {"current_chapter": 0, "current_stage": "waiting_for_review"})
    _write_json(tmp_path / "data" / "versions" / "chapter_001_versions.json", {"selected": {"source_type": "manual", "version": 1}})
    _write_version(tmp_path, "draft", 1, "draft_text", "draft")
    _write_version(tmp_path, "edited", 1, "edited_text", "edited")
    _write_version(tmp_path, "manual", 1, "manual_text", "manual")
    committed = tmp_path / "data" / "chapters" / "chapter_001.md"
    committed.parent.mkdir(parents=True, exist_ok=True)
    committed.write_text("# chapter 1\ncommitted", encoding="utf-8")

    monkeypatch.setattr(routes, "prepare_review_record", lambda data_dir="data": {"target": {"chapter_id": 1, "source_type": "manual"}, "record": {}})
    monkeypatch.setattr(routes.commands, "quality_summary_for_target", lambda target: {"overall_score": 1.0})
    monkeypatch.setattr(routes, "update_review_status", lambda chapter_id, status, decision="": {"status": status, "chapter_id": chapter_id})
    monkeypatch.setattr(routes, "save_review_markdown", lambda record, target, data_dir="data": "review.md")
    monkeypatch.setattr(routes.commands, "commit_chapter_command", lambda: {"status": "success", "message": "committed", "outputs": {}, "warnings": []})
    monkeypatch.setattr(routes.commands, "sync_obsidian_command", lambda: {"status": "success", "message": "ok", "outputs": {}, "warnings": []})
    monkeypatch.setattr(routes.commands, "index_vault_command", lambda: {"status": "success", "message": "ok", "outputs": {}, "warnings": []})

    result = routes.approve_review(polish=False)

    assert result["ok"] is True
    assert len(result["result"]["archived_versions"]) == 3
    assert committed.exists()
    assert not list((tmp_path / "data" / "drafts").glob("chapter_001_*"))
    assert not list((tmp_path / "data" / "edited").glob("chapter_001_*"))
    assert not list((tmp_path / "data" / "manual").glob("chapter_001_*"))
    for kind in ("draft", "edited", "manual"):
        assert (tmp_path / "data" / "archive" / "versions" / "chapter_001" / f"{kind}_v001" / "archive_meta.json").exists()
