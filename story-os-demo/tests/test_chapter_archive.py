from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from system.chapter_archive import ChapterArchiveError, archive_chapter
from system.context_builder import build_working_context
from system.status_dashboard import collect_progress_info
from system.version_manager import list_versions

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str = "text") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def prepare_chapter(root: Path, chapter_id: int, current_chapter: int = 1) -> None:
    data = root / "data"
    code = f"{chapter_id:03d}"
    write_text(data / "chapters" / f"chapter_{code}.md", f"# Chapter {chapter_id}\n\nbody")
    write_json(data / "summaries" / f"chapter_{code}_summary.json", {"chapter_id": chapter_id, "short_summary": f"summary {chapter_id}"})
    write_json(data / "drafts" / f"chapter_{code}_draft_v001.json", {"chapter_id": chapter_id, "draft_text": "draft"})
    write_text(data / "drafts" / f"chapter_{code}_draft_v001.md")
    write_json(data / "edited" / f"chapter_{code}_edited_v001.json", {"chapter_id": chapter_id, "edited_text": "edited"})
    write_text(data / "edited" / f"chapter_{code}_edited_v001.md")
    write_json(data / "manual" / f"chapter_{code}_manual_v001.json", {"chapter_id": chapter_id, "manual_text": "manual"})
    write_text(data / "manual" / f"chapter_{code}_manual_v001.md")
    write_json(data / "pipeline_runs" / f"run_chapter_{code}.json", {"chapter_id": chapter_id, "status": "success"})
    write_json(data / "state.json", {"current_chapter": current_chapter, "current_stage": "chapter_committed"})
    write_json(
        data / "memory" / "memory_index.json",
        {
            "memory_version": "0.6",
            "chapters": [
                {
                    "chapter_id": chapter_id,
                    "title": f"Chapter {chapter_id}",
                    "chapter_path": (data / "chapters" / f"chapter_{code}.md").as_posix(),
                    "summary_path": (data / "summaries" / f"chapter_{code}_summary.json").as_posix(),
                    "short_summary": f"summary {chapter_id}",
                    "memory_tags": ["tag"],
                }
            ],
        },
    )


def append_memory_chapter(root: Path, chapter_id: int) -> None:
    data = root / "data"
    memory_path = data / "memory" / "memory_index.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    code = f"{chapter_id:03d}"
    memory["chapters"].append(
        {
            "chapter_id": chapter_id,
            "title": f"Chapter {chapter_id}",
            "chapter_path": (data / "chapters" / f"chapter_{code}.md").as_posix(),
            "summary_path": (data / "summaries" / f"chapter_{code}_summary.json").as_posix(),
            "short_summary": f"summary {chapter_id}",
            "memory_tags": ["tag"],
        }
    )
    write_json(memory_path, memory)


def test_archive_chapter_succeeds_and_moves_related_files(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1)

    result = archive_chapter(1, tmp_path / "data")

    archive_dir = tmp_path / "data" / "archive" / "chapters" / "chapter_001"
    assert result["chapter"] == 1
    assert (archive_dir / "archive_meta.json").exists()
    assert (archive_dir / "chapters" / "chapter_001.md").exists()
    assert (archive_dir / "drafts" / "chapter_001_draft_v001.json").exists()
    assert (archive_dir / "edited" / "chapter_001_edited_v001.json").exists()
    assert (archive_dir / "manual" / "chapter_001_manual_v001.json").exists()
    assert (archive_dir / "summaries" / "chapter_001_summary.json").exists()
    assert (archive_dir / "pipeline_runs" / "run_chapter_001.json").exists()
    assert not (tmp_path / "data" / "chapters" / "chapter_001.md").exists()


def test_archived_chapter_disappears_from_normal_chapter_list(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1, current_chapter=2)
    prepare_chapter(tmp_path, 2, current_chapter=2)
    append_memory_chapter(tmp_path, 1)

    archive_chapter(1, tmp_path / "data")

    progress = collect_progress_info(tmp_path / "data")
    assert [item["chapter_id"] for item in progress["active_chapters"]] == [2]


def test_archived_chapter_disappears_from_version_list(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1)

    archive_chapter(1, tmp_path / "data")

    versions = list_versions(1, tmp_path / "data")
    assert versions["drafts"] == []
    assert versions["edited"] == []
    assert versions["manual"] == []


def test_archived_chapter_is_excluded_from_context_building(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1, current_chapter=2)
    prepare_chapter(tmp_path, 2, current_chapter=2)
    append_memory_chapter(tmp_path, 1)
    memory_path = tmp_path / "data" / "memory" / "memory_index.json"

    archive_chapter(1, tmp_path / "data")
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    context = build_working_context({"current_chapter": 2}, memory, "tag")

    assert all(item["chapter_id"] != 1 for item in context["recent_chapters"])
    assert all(item["chapter_id"] != 1 for item in context["retrieved_summaries"])


def test_archive_does_not_touch_unrelated_files(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1)
    unrelated = tmp_path / "data" / "drafts" / "chapter_002_draft_v001.json"
    write_json(unrelated, {"chapter_id": 2, "draft_text": "keep"})

    archive_chapter(1, tmp_path / "data")

    assert unrelated.exists()


def test_archive_missing_chapter_returns_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ChapterArchiveError, match="chapter_001 has no local files"):
        archive_chapter(1, tmp_path / "data")


def test_archive_permission_error_does_not_corrupt_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_chapter(tmp_path, 1)
    state_path = tmp_path / "data" / "state.json"
    before = state_path.read_text(encoding="utf-8")
    original_replace = Path.replace

    def guarded_replace(self: Path, target: Path) -> Path:
        if self.name == "chapter_001.md":
            raise PermissionError(self.as_posix())
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", guarded_replace)

    with pytest.raises(PermissionError):
        archive_chapter(1, tmp_path / "data")

    assert state_path.read_text(encoding="utf-8") == before


def test_archive_current_chapter_recalculates_current_chapter(tmp_path: Path) -> None:
    prepare_chapter(tmp_path, 1, current_chapter=2)
    prepare_chapter(tmp_path, 2, current_chapter=2)
    append_memory_chapter(tmp_path, 1)

    archive_chapter(2, tmp_path / "data")

    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))
    assert state["current_chapter"] == 1


def test_archive_chapter_api_returns_standard_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_chapter(tmp_path, 1)

    response = client.post("/api/chapters/1/archive")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["result"]["chapter"] == 1


def test_archive_ui_has_confirmation_copy() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "chapter-archive-panel" in html
    assert "chapter-archive-list" in html
    assert "function archiveChapter" in script
    assert "window.confirm" in script
    assert "/api/chapters/" in script

def test_version_archive_ui_has_discard_action() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")

    assert "function archiveVersion" in app_js
    assert "/api/versions/archive" in app_js
    assert "window.confirm" in app_js
    assert "\u5f03\u7528" in app_js
