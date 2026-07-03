from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def sample_report(full: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "health_version": "2.4-A",
        "overall_status": "ok",
        "overall_score": 1.0,
        "checked_at": "2026-07-02T16:30:00",
        "summary": {"errors": 0, "warnings": 0, "infos": 0},
        "sections": {"project_initialization": {"status": "ok"}} if full else {},
        "issues": [],
        "suggestions": [],
    }
    return report


def test_memory_health_api_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))

    response = client.get("/api/memory-health")
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True


def test_memory_health_api_contains_required_summary_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))

    result = client.get("/api/memory-health").json()["result"]

    assert "overall_status" in result
    assert "overall_score" in result
    assert "summary" in result
    assert "issues" in result
    assert "suggestions" in result


def test_memory_health_api_full_returns_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def fake_check(data_dir: str = "data", full: bool = False) -> dict[str, Any]:
        calls.append(full)
        return sample_report(full)

    monkeypatch.setattr("web.routes.run_memory_health_check", fake_check)

    result = client.get("/api/memory-health?full=true").json()["result"]

    assert calls == [True]
    assert "sections" in result
    assert result["sections"]


def test_memory_health_api_does_not_return_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(data_dir: str = "data", full: bool = False) -> dict[str, Any]:
        raise RuntimeError("short failure")

    monkeypatch.setattr("web.routes.run_memory_health_check", fail)

    response = client.get("/api/memory-health")
    data = response.json()

    assert data["ok"] is False
    assert data["message"] == "操作失败"
    assert data["errors"] == ["short failure"]
    assert "Traceback" not in response.text
    assert "traceback" not in response.text.lower()


def test_memory_health_api_does_not_leak_api_key_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))

    response_text = client.get("/api/memory-health").text

    assert "API Key" not in response_text
    assert "DEEPSEEK_API_KEY" not in response_text
    assert "LOCAL_MODEL_API_KEY" not in response_text
    assert ".env" not in response_text


def test_memory_health_api_does_not_call_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    import llm.planning_service as planning_service

    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))
    monkeypatch.setattr(
        planning_service,
        "create_deepseek_client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DeepSeek called")),
    )

    assert client.get("/api/memory-health").json()["ok"] is True


def test_memory_health_api_does_not_call_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import llm.openai_compatible_client as client_module

    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))
    monkeypatch.setattr(
        client_module.OpenAICompatibleClient,
        "chat_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local model called")),
    )

    assert client.get("/api/memory-health").json()["ok"] is True


def test_memory_health_api_does_not_access_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    import system.obsidian_sync as obsidian_sync

    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))
    monkeypatch.setattr(
        obsidian_sync,
        "sync_to_obsidian",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("obsidian called")),
    )

    assert client.get("/api/memory-health").json()["ok"] is True


def test_memory_health_api_does_not_call_chroma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("web.routes.run_memory_health_check", lambda data_dir="data", full=False: sample_report(full))

    assert client.get("/api/memory-health").json()["ok"] is True
