from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_writing_constraints_get_uses_story_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text(
        json.dumps({"focus": ["主线推进"], "avoid": ["水字数"], "anti_ai_style_rules": ["减少总结"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    response = client.get("/api/writing-constraints")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["chapter_word_count"] == {"min": 2500, "max": 4500}
    assert payload["result"]["must_follow"] == ["主线推进"]


def test_writing_constraints_post_updates_story_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text(json.dumps({"title": "测试"}, ensure_ascii=False), encoding="utf-8")

    response = client.post(
        "/api/writing-constraints",
        json={
            "chapter_word_count": {"min": 3200, "max": 5200},
            "pacing": "每章必须有目标和阻力",
            "chapter_structure": "开场承压，中段推进，结尾钩子",
            "must_follow": ["第三人称有限视角"],
            "must_avoid": ["灌水"],
            "ai_style_limits": ["减少不是A而是B"],
        },
    )
    payload = response.json()
    saved = json.loads((data_dir / "story_spec.json").read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert payload["ok"] is True
    assert saved["writing_constraints"]["chapter_word_count"] == {"min": 3200, "max": 5200}
    assert saved["anti_ai_style_rules"] == ["减少不是A而是B"]
