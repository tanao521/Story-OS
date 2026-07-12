from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_index_returns_200() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Story OS Web Console" in response.text


def test_status_returns_200(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.build_status_dashboard",
        lambda full=True: {"dashboard_version": "2.1", "full": full},
    )

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["full"] is True


def test_run_chapter_uses_auto_commit_false(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_run_chapter_command(auto_commit: bool = True, require_model: bool = False) -> dict[str, Any]:
        called["auto_commit"] = auto_commit
        called["require_model"] = require_model
        return {"status": "success", "message": "ok", "outputs": {"stage": "waiting_for_review"}, "warnings": []}

    monkeypatch.setattr("web.routes.commands.run_chapter_command", fake_run_chapter_command, raising=False)

    response = client.post("/api/run-chapter")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called["auto_commit"] is False
    assert called["require_model"] is True


def test_quality_check_returns_standard_response(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.commands.quality_check_command",
        lambda: {"status": "success", "message": "done", "outputs": {"score": 0.8}, "warnings": []},
    )

    response = client.post("/api/quality-check")
    data = response.json()

    assert set(["ok", "message", "result", "warnings", "errors"]).issubset(data)
    assert data["result"]["score"] == 0.8


def test_versions_returns_lists(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.commands.compare_drafts_command",
        lambda select_spec=None: {
            "status": "success",
            "message": "versions",
            "outputs": {"drafts": [{"version": 1}], "edited": [], "selected": None},
            "warnings": [],
        },
    )

    response = client.get("/api/versions")

    assert response.json()["drafts"] == [{"version": 1}]
    assert response.json()["edited"] == []


def test_select_version_handles_source_and_version(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_compare(select_spec: str | None = None) -> dict[str, Any]:
        called["select_spec"] = select_spec
        return {"status": "success", "message": "selected", "outputs": {"selected": {"version": 1}}, "warnings": []}

    monkeypatch.setattr("web.routes.commands.compare_drafts_command", fake_compare)

    response = client.post("/api/versions/select", json={"source_type": "edited", "version": 1})

    assert response.json()["ok"] is True
    assert called["select_spec"] == "edited:1"


def test_ask_supports_modes(monkeypatch: Any) -> None:
    monkeypatch.setattr("web.routes.answer_from_state", lambda question: {"mode": "state", "warnings": []})
    monkeypatch.setattr("web.routes.answer_from_memory", lambda question, use_vector=True: {"mode": "memory", "warnings": []})
    monkeypatch.setattr(
        "web.routes.answer_from_story",
        lambda question, use_llm=False, use_vector=True: {"mode": "story", "warnings": []},
    )

    for mode in ["state", "memory", "story"]:
        response = client.post("/api/ask", json={"mode": mode, "question": "test"})
        assert response.json()["result"]["qa"]["mode"] == mode


def test_todos_list_and_create(monkeypatch: Any) -> None:
    monkeypatch.setattr("web.routes.list_todos", lambda status="open": [{"id": 1, "title": "x"}])
    monkeypatch.setattr(
        "web.routes.create_todo",
        lambda title, todo_type="other", priority="medium", chapter_id=None: {
            "id": 2,
            "title": title,
            "type": todo_type,
            "priority": priority,
            "chapter_id": chapter_id,
        },
    )

    assert client.get("/api/todos").json() == [{"id": 1, "title": "x"}]
    created = client.post("/api/todos", json={"title": "fix", "type": "revision", "priority": "medium"}).json()
    assert created["result"]["todo"]["title"] == "fix"


def test_errors_do_not_expose_traceback(monkeypatch: Any) -> None:
    def boom() -> dict[str, Any]:
        raise RuntimeError("simple failure")

    monkeypatch.setattr("web.routes.commands.quality_check_command", boom)

    response = client.post("/api/quality-check")
    data = response.json()

    assert data["ok"] is False
    assert "Traceback" not in response.text
    assert data["errors"] == ["simple failure"]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prepare_version_api_files(root: Path) -> None:
    _write_json(root / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    _write_json(
        root / "data" / "drafts" / "chapter_001_draft_v001.json",
        {"chapter_id": 1, "version_label": "draft_v001", "draft_text": "draft text"},
    )
    _write_json(
        root / "data" / "edited" / "chapter_001_edited_v001.json",
        {"chapter_id": 1, "version_label": "edited_v001", "edited_text": "edited text", "source_draft_version": 1},
    )
    _write_json(
        root / "data" / "manual" / "chapter_001_manual_v001.json",
        {
            "chapter_id": 1,
            "version_label": "manual_v001",
            "manual_text": "manual text",
            "source_type": "edited",
            "source_version": 1,
        },
    )


def test_versions_api_ignores_pipeline_runs_and_returns_real_versions(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_version_api_files(tmp_path)
    pipeline_dir = tmp_path / "data" / "pipeline_runs"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "run_chapter_001.json").write_text("{not valid json", encoding="utf-8")

    response = client.get("/api/versions")

    assert response.status_code == 200
    data = response.json()
    assert [item["version_label"] for item in data["drafts"]] == ["draft_v001"]
    assert [item["version_label"] for item in data["edited"]] == ["edited_v001"]
    assert [item["version_label"] for item in data["manual"]] == ["manual_v001"]
    all_paths = [item["json_path"] for key in ["drafts", "edited", "manual"] for item in data[key]]
    assert not any("pipeline_runs" in path for path in all_paths)


def test_versions_api_does_not_read_unreadable_pipeline_run(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_version_api_files(tmp_path)
    pipeline_path = tmp_path / "data" / "pipeline_runs" / "run_chapter_001.json"
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if "pipeline_runs" in path.parts:
            raise PermissionError(path.as_posix())
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    response = client.get("/api/versions")

    assert response.status_code == 200
    assert response.json()["drafts"][0]["version_label"] == "draft_v001"


def test_versions_api_falls_back_when_command_hits_permission_error(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_version_api_files(tmp_path)

    def raise_permission(select_spec: str | None = None) -> dict[str, Any]:
        raise PermissionError(r"data\pipeline_runs\run_chapter_001.json")

    monkeypatch.setattr("web.routes.commands.compare_drafts_command", raise_permission)

    response = client.get("/api/versions")

    assert response.status_code == 200
    data = response.json()
    assert [item["version_label"] for item in data["drafts"]] == ["draft_v001"]
    assert [item["version_label"] for item in data["edited"]] == ["edited_v001"]
    assert data["errors"] == [r"data\pipeline_runs\run_chapter_001.json"]

def test_archive_version_api_archives_current_chapter_version(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_version_api_files(tmp_path)

    response = client.post("/api/versions/archive", json={"source_type": "draft", "version": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["result"]["archive_meta_path"].endswith("archive_meta.json")
    assert client.get("/api/versions").json()["drafts"] == []


def test_quality_check_can_target_current_preview_version(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_quality_check_command(**kwargs: Any) -> dict[str, Any]:
        called.update(kwargs)
        return {"status": "success", "message": "done", "outputs": {"report_count": 1}, "warnings": []}

    monkeypatch.setattr("web.routes.commands.quality_check_command", fake_quality_check_command)

    response = client.post("/api/quality-check", json={"source_type": "draft", "version": 2})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called == {"draft_version": 2}
