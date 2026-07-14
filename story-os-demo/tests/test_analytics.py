from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from analytics.service import AnalyticsService
from core.project_context import get_project_context
from web.app import app


def _project(tmp_path: Path, title: str, genre: str = "末世") -> Path:
    root = tmp_path / title
    (root / "data" / "chapters").mkdir(parents=True)
    (root / "data" / "story_spec.json").write_text('{"title":"测试作品","genre":"' + genre + '","focus":["生存","团队成长"]}', encoding="utf-8")
    (root / "data" / "chapters" / "chapter_001.md").write_text("危机突然降临。主角决定保护同伴，却发现门后藏着秘密？", encoding="utf-8")
    return root


def test_analytics_is_project_scoped_and_marks_sources(tmp_path: Path) -> None:
    first, second = _project(tmp_path, "first"), _project(tmp_path, "second", "悬疑")
    one = AnalyticsService(get_project_context(first)); two = AnalyticsService(get_project_context(second))
    market_one, market_two = one.market(), two.market()
    assert market_one["source"] == "rule_based"
    assert market_one["genre"] == "末世" and market_two["genre"] == "悬疑"
    assert one.chapter(1)["score"].keys() >= {"hook_score", "emotion_score", "conflict_score", "character_score", "world_score", "pacing_score", "ending_hook_score"}
    one.update_profile({"market_position": "高压生存"})
    assert one.profile()["market_position"] == "高压生存"
    assert two.profile()["market_position"] == ""


def test_analytics_api_uses_active_project_context(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path, "api-project")
    monkeypatch.chdir(root)
    with TestClient(app) as client:
        market = client.post("/api/analytics/market").json()
        chapter = client.get("/api/analytics/chapter/1").json()
        report = client.get("/api/analytics/report").json()
    assert market["ok"] and market["result"]["market"]["source"] == "rule_based"
    assert chapter["result"]["chapter"]["score"]["total"] >= 0
    assert report["result"]["report"]["source"] == "rule_based"
