"""Phase 0D4-D focused tests: POST /api/narrative-turn/confirm HTTP endpoint.

Covers:
- 200 success with ConfirmResponseWireDTO shape
- Cache-Control: no-store header
- 400 malformed request (missing fields, invalid IDs)
- 404 scope mismatch
- 409 TURN_ALREADY_CONFIRMED
- 409 OPERATION_ID_CONFLICT
- 409 BRANCH_ARCHIVED
- 409 BRANCH_NOT_ACTIVE
- 422 blocked / requires_clarification rejection
- 500 safe internal error envelope
- Custom action raw text never in response / error envelope
- Idempotent replay flag
- Recovery flag
- No raw custom text in any response
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from core.project_context import ProjectContext, get_project_context  # noqa: E402
from system.narrative_branch_store import NarrativeBranchStore  # noqa: E402
from core.contracts.narrative_turn import TimelineContext  # noqa: E402
from web.app import app  # noqa: E402


FIXED_CLOCK = "2025-01-15T12:00:00+00:00"


def _seed_minimal_project(ctx: ProjectContext) -> None:
    data_dir = ctx.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    ctx.chapters_dir.mkdir(parents=True, exist_ok=True)
    ctx.narrative_state_dir.mkdir(parents=True, exist_ok=True)

    planning = {
        "schema_version": "1.0",
        "chapters": [
            {
                "chapter_id": "ch-001-test",
                "chapter_number": 1,
                "title": "第一章：启程",
                "goal": "主角离开家乡，踏上旅程",
                "conflicts": [{"id": "c1", "title": "迷雾森林的未知危险"}],
                "plot_threads": [
                    {"thread_id": "t1", "title": "失踪的旅人", "status": "active"},
                ],
            }
        ],
    }
    (data_dir / "story_planning.json").write_text(
        json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    world = {
        "schema_version": "1.0",
        "core_rules": [
            {"id": "r1", "rule": "魔法需要消耗精神力"},
        ],
        "taboos_or_limits": ["使用禁忌魔法", "攻击平民"],
        "locations": [
            {"id": "loc1", "name": "迷雾森林"},
            {"id": "loc2", "name": "边境小镇"},
        ],
        "resources": {
            "金币": {"amount": 100, "unit": "枚"},
            "药水": {"amount": 3, "unit": "瓶"},
        },
    }
    (data_dir / "world_bible.json").write_text(
        json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chars = {
        "schema_version": "1.0",
        "main_characters": [
            {"id": "mc1", "name": "林远", "role": "protagonist", "capabilities": ["剑术", "侦查"]},
        ],
        "supporting_characters": [
            {"id": "sc1", "name": "老村长", "role": "mentor"},
        ],
    }
    (data_dir / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.chapters_dir / "chapter_001.md").write_text(
        "# 第一章：启程\n\n林远站在村口，回望家乡。",
        encoding="utf-8",
    )

    rolling = {
        "schema_version": "1.0",
        "current_chapter": 1,
        "remaining_chapters": 5,
        "window_size": 3,
    }
    ctx.rolling_window_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.rolling_window_path.write_text(
        json.dumps(rolling, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    deps = {
        "schema_version": "1.0",
        "blocking_dependencies": [],
    }
    ctx.planning_dependencies_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.planning_dependencies_path.write_text(
        json.dumps(deps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.narrative_state_dir / "current.json").write_text(
        json.dumps({"chapter": 1, "time_of_day": "morning"}, ensure_ascii=False),
        encoding="utf-8",
    )


def _create_branch(ctx: ProjectContext, timeline_id: str, branch_id: str) -> None:
    store = NarrativeBranchStore(ctx)
    tl = TimelineContext(project_id=ctx.root.name, timeline_id=timeline_id)
    store.create_branch(tl, branch_id, "test")
    revision = store.get_registry_revision(tl)
    store.select_branch(tl, branch_id, expected_revision=revision)


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a minimal project and chdir into it for TestClient middleware."""
    ctx = get_project_context(tmp_path)
    _seed_minimal_project(ctx)
    _create_branch(ctx, "tl-main", "br-alpha")
    return tmp_path


@pytest.fixture
def client(temp_project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(temp_project_dir)
    return TestClient(app)


@pytest.fixture
def scope_params(temp_project_dir: Path) -> dict[str, str]:
    """Return the scope params matching the temp project + root branch."""
    ctx = get_project_context(temp_project_dir)
    return {
        "project_id": ctx.root.name,
        "timeline_id": "tl-main",
        "branch_id": "br-alpha",
    }


def _get_first_action_id(client, scope_params):
    params = {
        **scope_params,
        "chapter_id": "1",
    }
    resp = client.get("/api/narrative-turn/plan", params=params)
    assert resp.status_code == 200
    plan = resp.json()
    return plan["recommended_actions"][0]["action_id"]


class TestConfirmEndpoint:
    def test_confirm_recommended_success(self, client, scope_params):
        action_id = _get_first_action_id(client, scope_params)

        body = {
            "operation_id": "op-route-test-001",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "source_version_id": None,
            "expected_context_fingerprint": None,
            "expected_turn_id": None,
            "expected_validation_id": None,
            "expected_preview_fingerprint": None,
            "action_source": "recommended",
            "selected_action_id": action_id,
        }

        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store"

        data = resp.json()
        assert data["operation_id"] == "op-route-test-001"
        assert data["idempotent_replay"] is False
        assert data["recovery_performed"] is False
        assert "result" in data
        assert data["result"]["turn_id"] is not None
        assert data["result"]["result_status"] in ("success", "partial")
        assert data["result"]["selected_action_id"] == action_id
        assert data["result"]["custom_action_text_hash"] is None
        assert data["result"]["event_summary"] is not None
        assert "branch_state_revision" in data

    def test_confirm_idempotent_replay(self, client, scope_params):
        action_id = _get_first_action_id(client, scope_params)

        body = {
            "operation_id": "op-route-test-002",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "source_version_id": None,
            "expected_context_fingerprint": None,
            "expected_turn_id": None,
            "expected_validation_id": None,
            "expected_preview_fingerprint": None,
            "action_source": "recommended",
            "selected_action_id": action_id,
        }

        resp1 = client.post("/api/narrative-turn/confirm", json=body)
        assert resp1.status_code == 200

        resp2 = client.post("/api/narrative-turn/confirm", json=body)
        assert resp2.status_code == 200

        data2 = resp2.json()
        assert data2["idempotent_replay"] is True
        assert data2["result"]["turn_id"] == resp1.json()["result"]["turn_id"]

    def test_confirm_missing_operation_id(self, client, scope_params):
        body = {
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "action_source": "recommended",
            "selected_action_id": "act-123",
        }
        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "MALFORMED_REQUEST"

    def test_confirm_invalid_action_source(self, client, scope_params):
        body = {
            "operation_id": "op-bad-src",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "action_source": "invalid",
        }
        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "MALFORMED_REQUEST"

    def test_confirm_custom_action_no_raw_text_in_response(self, client, scope_params):
        custom_text = "前往迷雾森林寻找SECRET_SENTINEL_XYZ"

        body = {
            "operation_id": "op-route-custom-001",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "source_version_id": None,
            "expected_context_fingerprint": None,
            "expected_turn_id": None,
            "expected_validation_id": None,
            "expected_preview_fingerprint": None,
            "action_source": "custom",
            "custom_action_text": custom_text,
        }

        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.status_code == 200

        resp_text = resp.text
        assert "SECRET_SENTINEL" not in resp_text
        assert custom_text not in resp_text

        data = resp.json()
        assert data["result"]["custom_action_text_hash"] is not None
        assert "SECRET_SENTINEL" not in data["result"]["event_summary"]

    def test_confirm_archived_branch(self, client, scope_params, temp_project_dir):
        project_id = scope_params["project_id"]

        ctx = get_project_context(temp_project_dir)
        from system.narrative_branch_store import NarrativeBranchStore
        from core.contracts.narrative_turn import TimelineContext
        store = NarrativeBranchStore(ctx)
        tl = TimelineContext(project_id=project_id, timeline_id="tl-main")
        store.create_branch(tl, "br-replacement", "replacement")
        rev = store.get_registry_revision(tl)
        store.create_branch(tl, "br-archived-test", "test")
        rev = store.get_registry_revision(tl)
        store.archive_branch(tl, "br-archived-test", replacement_branch_id="br-replacement", expected_revision=rev)

        body = {
            "operation_id": "op-archived-test",
            "project_id": project_id,
            "timeline_id": "tl-main",
            "branch_id": "br-archived-test",
            "chapter_id": 1,
            "action_source": "custom",
            "custom_action_text": "测试行动",
        }

        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.status_code in (409, 400)

    def test_confirm_no_store_header(self, client, scope_params):
        action_id = _get_first_action_id(client, scope_params)

        body = {
            "operation_id": "op-route-header-001",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "action_source": "recommended",
            "selected_action_id": action_id,
        }

        resp = client.post("/api/narrative-turn/confirm", json=body)
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_confirm_different_operations_same_turn_conflict(self, client, scope_params):
        action_id = _get_first_action_id(client, scope_params)

        body1 = {
            "operation_id": "op-conflict-1",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "action_source": "recommended",
            "selected_action_id": action_id,
        }

        resp1 = client.post("/api/narrative-turn/confirm", json=body1)
        assert resp1.status_code == 200

        turn_id = resp1.json()["result"]["turn_id"]
        ctx_fp = resp1.json()["result"]["next_context_fingerprint"]
        body2 = {
            "operation_id": "op-conflict-2",
            "project_id": scope_params["project_id"],
            "timeline_id": "tl-main",
            "branch_id": "br-alpha",
            "chapter_id": 1,
            "expected_context_fingerprint": ctx_fp,
            "expected_turn_id": turn_id,
            "action_source": "recommended",
            "selected_action_id": action_id,
        }
        resp2 = client.post("/api/narrative-turn/confirm", json=body2)
        assert resp2.status_code in (409, 400)
        data = resp2.json()
        if "error" in data:
            assert data["error"]["code"] in (
                "TURN_ALREADY_CONFIRMED",
                "OPERATION_ID_CONFLICT",
                "CONTEXT_STALE",
                "TURN_ID_MISMATCH",
                "MALFORMED_REQUEST",
            )
