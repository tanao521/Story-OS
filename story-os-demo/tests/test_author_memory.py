from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from author_memory.asset_store import AuthorAssetStore
from author_memory.author_profile import AuthorProfileService
from author_memory.knowledge_retriever import AuthorKnowledgeRetriever
from author_memory.preference_engine import resolve_preferences
from core.project_context import get_project_context
from system.context_builder import build_working_context
from web.app import app


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"; (workspace / ".story_os").mkdir(parents=True)
    first, second = workspace / "projects" / "one", workspace / "projects" / "two"
    for root, title in ((first, "One"), (second, "Two")):
        (root / "data").mkdir(parents=True)
        (root / "data" / "story_spec.json").write_text('{"title":"' + title + '","avoid":["slow pacing"]}', encoding="utf-8")
    return workspace, first, second


def test_author_assets_share_but_project_data_does_not(tmp_path: Path) -> None:
    _, first, second = _workspace(tmp_path)
    one, two = get_project_context(first), get_project_context(second)
    AuthorProfileService(one).update({"name": "Mock Author", "avoid_patterns": ["long exposition"]})
    asset = AuthorAssetStore(one).add_asset({"name": "Shelter world", "category": "worlds", "content": "survival shelter rules", "tags": ["survival"]})
    assert AuthorProfileService(two).profile()["name"] == "Mock Author"
    assert any(row["id"] == asset["id"] for row in AuthorAssetStore(two).list_assets("shelter"))
    assert not (second / "data" / "creative_assets").exists()


def test_preference_conflict_and_retrieval_are_advisory(tmp_path: Path) -> None:
    _, first, _ = _workspace(tmp_path); context = get_project_context(first)
    preferences = AuthorProfileService(context).update_preferences({"preferences": [{"type": "avoid", "category": "pace", "content": "slow pacing"}]})
    AuthorAssetStore(context).add_asset({"name": "Opening lesson", "category": "plots", "content": "opening conflict must appear early"})
    conflict = resolve_preferences(preferences, ["fast pacing with high density conflict"])
    assert conflict["auto_override"] is False and conflict["priority_order"][0] == "author_explicit"
    recalled = AuthorKnowledgeRetriever(context).retrieve("opening conflict")
    assert recalled and recalled[0]["source"] == "author_asset"


def test_context_exposes_author_global_without_project_assets(tmp_path: Path, monkeypatch) -> None:
    workspace, first, _ = _workspace(tmp_path); monkeypatch.chdir(first)
    AuthorProfileService(get_project_context(first)).update_preferences({"preferences": [{"type": "preference", "category": "dialogue", "content": "concise dialogue"}]})
    context = build_working_context({"current_chapter": 0}, {"chapters": []}, "dialogue", {"title": "One"}, {}, {})
    assert context["context_order"][1] == "author_global"
    assert "concise dialogue" in context["author_global"]["preferences"]
    assert "Two" not in str(context["author_global"])


def test_author_api_round_trip(tmp_path: Path, monkeypatch) -> None:
    workspace, _, _ = _workspace(tmp_path); monkeypatch.chdir(workspace)
    with TestClient(app) as client:
        saved = client.put("/api/author/profile", json={"name": "API Author"}).json()
        added = client.post("/api/author/assets", json={"name": "Scene seed", "content": "a locked train", "category": "scenes"}).json()
        loaded = client.get("/api/author/assets?query=train").json()
    assert saved["ok"] and saved["result"]["profile"]["name"] == "API Author"
    assert added["ok"] and any(row["name"] == "Scene seed" for row in loaded["result"]["assets"])
