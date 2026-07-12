from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_llm_health_api_returns_cloud_report(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "web.routes.build_llm_health_report",
        lambda: {
            "provider": "api",
            "base_url": "https://api.openai.com/v1",
            "model": "deepseek-v4-pro:cloud",
            "has_api_key": True,
            "ok": True,
            "test_generation_ok": True,
            "error_message": "",
        },
    )

    response = client.get("/api/llm/health")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "api"
    assert data["ok"] is True
    assert data["test_generation_ok"] is True
