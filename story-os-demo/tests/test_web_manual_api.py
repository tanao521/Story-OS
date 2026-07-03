from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prose() -> str:
    base = (
        "雨水沿着避难所的玻璃顶棚往下淌，像一行行没有写完的字。"
        "林岚站在闸门前，听见广播里重复播报同一个不存在的房间号。"
        "她把钥匙插进锁孔时，身后的孩子忽然停止哭泣，因为门内有人用她父亲的声音说，欢迎回来。"
        "那一刻，所有人都知道，这座避难所保存下来的不只是食物和电力。"
    )
    return base * 2


def prepare_versions(root: Path) -> None:
    write_json(root / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    write_json(
        root / "data" / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": prose(),
            "editing": {"mode": "deepseek", "fallback_used": False},
        },
    )


def test_manual_save_api_creates_manual(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)

    response = client.post(
        "/api/manual/save",
        json={"chapter_id": 1, "source_type": "edited", "source_version": 1, "text": prose()},
    )
    data = response.json()

    assert data["ok"] is True
    assert data["result"]["source_type"] == "manual"
    assert data["result"]["version_label"] == "manual_v001"
    assert (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()


def test_manual_save_api_rejects_empty(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)

    response = client.post(
        "/api/manual/save",
        json={"chapter_id": 1, "source_type": "edited", "source_version": 1, "text": ""},
    )
    data = response.json()

    assert data["ok"] is False
    assert data["errors"]


def test_version_content_supports_manual(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)
    client.post("/api/manual/save", json={"chapter_id": 1, "source_type": "edited", "source_version": 1, "text": prose()})

    response = client.get("/api/versions/content?source_type=manual&version=1")

    assert response.json()["ok"] is True
    assert response.json()["result"]["source_type"] == "manual"
    assert response.json()["result"]["text"] == prose()


def test_versions_api_returns_manual(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)
    client.post("/api/manual/save", json={"chapter_id": 1, "source_type": "edited", "source_version": 1, "text": prose()})

    response = client.get("/api/versions")

    assert response.json()["manual"][0]["version_label"] == "manual_v001"
    assert "sk-" not in response.text
