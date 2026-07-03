from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)
STANDARD_KEYS = {"ok", "message", "result", "warnings", "errors"}


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/run-chapter", {}),
        ("/api/quality-check", {}),
        ("/api/versions/select", {"source_type": "edited", "version": 1}),
        ("/api/review/reject", {}),
        ("/api/review/later", {}),
        ("/api/todos", {"title": "todo", "type": "revision", "priority": "medium"}),
        ("/api/todos/1/done", {}),
        ("/api/todos/1/reopen", {}),
        ("/api/todos/1/cancel", {}),
        ("/api/ask", {"mode": "state", "question": "test"}),
        ("/api/sync-obsidian", {}),
        ("/api/index-vault", {}),
    ],
)
def test_post_apis_return_standard_shape(monkeypatch: Any, path: str, body: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "web.routes.commands.run_chapter_command",
        lambda auto_commit=False: {"status": "success", "message": "ok", "outputs": {}, "warnings": []},
        raising=False,
    )
    monkeypatch.setattr(
        "web.routes.commands.quality_check_command",
        lambda: {"status": "success", "message": "ok", "outputs": {}, "warnings": []},
    )
    monkeypatch.setattr(
        "web.routes.commands.compare_drafts_command",
        lambda select_spec=None: {"status": "success", "message": "ok", "outputs": {}, "warnings": []},
    )
    monkeypatch.setattr(
        "web.routes.prepare_review_record",
        lambda data_dir="data": {"target": {"chapter_id": 1}, "record": {"chapter_id": 1}},
    )
    monkeypatch.setattr("web.routes.update_review_status", lambda chapter_id, status, decision="", notes="", data_dir="data": {"status": status})
    monkeypatch.setattr("web.routes.save_review_markdown", lambda record, target, data_dir="data": "review.md")
    monkeypatch.setattr("web.routes.create_todo", lambda title, todo_type="other", priority="medium", chapter_id=None: {"id": 1, "title": title, "type": todo_type, "priority": priority, "chapter_id": chapter_id})
    monkeypatch.setattr("web.routes.update_todo_status", lambda todo_id, status: {"id": todo_id, "status": status})
    monkeypatch.setattr("web.routes.answer_from_state", lambda question: {"answer": "ok", "warnings": []})
    monkeypatch.setattr(
        "web.routes.commands.sync_obsidian_command",
        lambda: {"status": "success", "message": "ok", "outputs": {}, "warnings": []},
    )
    monkeypatch.setattr(
        "web.routes.commands.index_vault_command",
        lambda: {"status": "success", "message": "ok", "outputs": {}, "warnings": []},
    )

    response = client.post(path, json=body)

    assert response.status_code == 200
    assert STANDARD_KEYS.issubset(response.json())


def test_review_approve_low_score_requires_confirm(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.prepare_review_record",
        lambda data_dir="data": {"target": {"chapter_id": 1, "version": 1}, "record": {"chapter_id": 1}},
    )
    monkeypatch.setattr("web.routes.commands.quality_summary_for_target", lambda target: {"overall_score": 0.5})

    response = client.post("/api/review/approve", json={"force": False})
    data = response.json()

    assert data["ok"] is False
    assert data["need_confirm"] is True


def test_web_routes_do_not_read_sensitive_config_files() -> None:
    text = Path("web/routes.py").read_text(encoding="utf-8")

    assert ".env" not in text
    assert "API Key" not in text


def test_web_contract_tests_do_not_call_external_services(monkeypatch: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("external service should not be called")

    monkeypatch.setattr("web.routes.commands.sync_obsidian_command", forbidden)
    monkeypatch.setattr("web.routes.commands.index_vault_command", forbidden)

    response = client.get("/api/status")

    assert response.status_code == 200

def test_memory_health_api_returns_standard_shape(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.run_memory_health_check",
        lambda data_dir="data", full=False: {
            "health_version": "2.4-A",
            "overall_status": "ok",
            "overall_score": 1.0,
            "summary": {"errors": 0, "warnings": 0, "infos": 0},
            "sections": {},
            "issues": [],
            "suggestions": [],
        },
    )

    response = client.get("/api/memory-health")
    data = response.json()

    assert response.status_code == 200
    assert STANDARD_KEYS.issubset(data)
    assert data["ok"] is True
    assert "overall_status" in data["result"]
    assert "overall_score" in data["result"]
    assert "summary" in data["result"]
    assert "Traceback" not in response.text
    assert "API Key" not in response.text
    assert ".env" not in response.text
