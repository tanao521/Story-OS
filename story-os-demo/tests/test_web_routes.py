from __future__ import annotations

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

    def fake_run_chapter_command(auto_commit: bool = True) -> dict[str, Any]:
        called["auto_commit"] = auto_commit
        return {"status": "success", "message": "ok", "outputs": {"stage": "waiting_for_review"}, "warnings": []}

    monkeypatch.setattr("web.routes.commands.run_chapter_command", fake_run_chapter_command, raising=False)

    response = client.post("/api/run-chapter")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called["auto_commit"] is False


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
