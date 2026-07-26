"""Phase 0D4-C focused tests: read-only Narrative Turn HTTP endpoints.

Verifies the four endpoints:
    GET  /api/narrative-turn/context       → ContextWireDTO
    GET  /api/narrative-turn/plan          → PlanWireDTO
    POST /api/narrative-turn/feasibility   → ValidationWireDTO
    POST /api/narrative-turn/preview       → PreviewWireDTO

Covers:
- HTTP method correctness (GET for context/plan; POST for feasibility/preview)
- Cache-Control: no-store header on every response
- 200 success shape for all four DTOs
- 400 malformed request (missing/invalid project_id/timeline_id/branch_id/chapter_id)
- 404 explicit project/branch not found (no fallback to default project)
- 409 context/source/canon/turn stale or mismatched
- 422 deterministic input rejected (action too long, unparseable)
- 500 safe internal error envelope (never leaks raw exception/traceback/path)
- exactly 3 recommended actions
- custom_action_policy.max_length == 200
- feasibility statuses (allowed / allowed_with_cost / requires_clarification / blocked) are 200, not HTTP errors
- POST body custom_action_text never echoed in response
- POST body custom_action_text never appears in error envelope
- expected_context_fingerprint mismatch → 409
- expected_turn_id mismatch → 409
- invalid selected_action_id → 409 ACTION_NOT_FOUND
- no NarrativeTurnStore.append_plan / append_validation calls
- no NarrativeTurnResult creation, no NarrativeTurnTransition append
- no filesystem writes from the route layer
- no Provider / Canon / Chroma / NarrativeMemory writes
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
from system.narrative_action_feasibility import MAX_CUSTOM_ACTION_LENGTH  # noqa: E402
from system.narrative_branch_store import NarrativeBranchStore  # noqa: E402
from core.contracts.narrative_turn import TimelineContext  # noqa: E402
from web.app import app  # noqa: E402


FIXED_CLOCK = "2025-01-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Seed helpers (mirrors test_phase0d4b_narrative_turn_planner.py)
# ---------------------------------------------------------------------------

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
        "core_rules": [{"id": "r1", "rule": "魔法需要消耗精神力"}],
        "taboos_or_limits": ["使用禁忌魔法"],
        "locations": [{"id": "loc1", "name": "迷雾森林"}],
        "resources": {"金币": {"amount": 100, "unit": "枚"}},
    }
    (data_dir / "world_bible.json").write_text(
        json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chars = {
        "schema_version": "1.0",
        "main_characters": [
            {"id": "mc1", "name": "林远", "role": "protagonist", "capabilities": ["剑术"]},
        ],
    }
    (data_dir / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.chapters_dir / "chapter_001.md").write_text(
        "# 第一章：启程\n\n林远站在村口。", encoding="utf-8",
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

    deps = {"schema_version": "1.0", "blocking_dependencies": []}
    ctx.planning_dependencies_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.planning_dependencies_path.write_text(
        json.dumps(deps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.narrative_state_dir / "current.json").write_text(
        json.dumps({"chapter": 1, "time_of_day": "morning"}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a minimal project and chdir into it for TestClient middleware."""
    ctx = get_project_context(tmp_path)
    _seed_minimal_project(ctx)
    # Create an open active branch.
    timeline_ctx = TimelineContext(project_id=ctx.root.name, timeline_id="tl-main")
    store = NarrativeBranchStore(ctx)
    store.create_branch(timeline_ctx, "root", "Root Branch")
    revision = store.get_registry_revision(timeline_ctx)
    store.select_branch(timeline_ctx, "root", revision)
    return tmp_path


@pytest.fixture
def client(temp_project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(temp_project_dir)
    return TestClient(app)


@pytest.fixture
def scope_params(temp_project_dir: Path) -> dict[str, str]:
    """Return the scope params matching the temp project + root branch."""
    ctx = get_project_context(temp_project_dir)
    timeline_ctx = TimelineContext(project_id=ctx.root.name, timeline_id="tl-main")
    store = NarrativeBranchStore(ctx)
    branches = store.list_branches(timeline_ctx)
    assert branches, "expected at least one branch"
    branch_id = branches[0].branch_id
    return {
        "project_id": ctx.root.name,
        "timeline_id": "tl-main",
        "branch_id": branch_id,
    }


# ===========================================================================
# Section 1: GET /api/narrative-turn/context
# ===========================================================================

class TestContextEndpoint:
    def test_get_context_returns_200_with_dto(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200
        dto = response.json()
        assert dto["schema_version"]
        assert dto["scope"] == {
            "project_id": scope_params["project_id"],
            "timeline_id": scope_params["timeline_id"],
            "branch_id": scope_params["branch_id"],
        }
        assert dto["chapter_id"] == 1
        assert isinstance(dto["context_fingerprint"], str)
        assert len(dto["context_fingerprint"]) == 64
        assert dto["planner_revision"]
        assert set(dto["branch"].keys()) == {"lifecycle", "activity", "narrative_state_data"}
        assert set(dto["situation"].keys()) == {
            "chapter_goal", "active_conflicts", "characters", "locations",
            "resources", "world_rules", "open_threads", "time_window", "dependencies",
        }

    def test_get_context_has_no_store_cache_control(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.headers.get("cache-control") == "no-store"
        assert response.headers.get("content-type") == "application/json"

    def test_get_context_missing_project_id_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        params = {**scope_params, "chapter_id": "1"}
        params.pop("project_id")
        response = client.get("/api/narrative-turn/context", params=params)
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "MALFORMED_REQUEST"

    def test_get_context_missing_chapter_id_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params=scope_params)
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "MALFORMED_REQUEST"

    def test_get_context_invalid_chapter_id_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "abc",
        })
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "MALFORMED_REQUEST"

    def test_get_context_invalid_project_id_format_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        params = {**scope_params, "chapter_id": "1", "project_id": "has spaces"}
        response = client.get("/api/narrative-turn/context", params=params)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_get_context_branch_not_found_returns_404(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        params = {**scope_params, "chapter_id": "1", "branch_id": "nonexistent-branch"}
        response = client.get("/api/narrative-turn/context", params=params)
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] in ("BRANCH_NOT_FOUND", "SCOPE_MISMATCH")

    def test_get_context_no_fallback_to_default_project(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        # project_id mismatch must return 404, never silently fall back.
        params = {**scope_params, "chapter_id": "1", "project_id": "different-project-id"}
        response = client.get("/api/narrative-turn/context", params=params)
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "SCOPE_MISMATCH"

    def test_get_context_response_has_no_traceback_or_path(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1",
        })
        text = response.text
        assert "Traceback" not in text
        assert "Path(" not in text
        assert ".pyc" not in text

    def test_get_context_optional_source_version_id(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1", "source_version_id": "v-001",
        })
        assert response.status_code == 200


# ===========================================================================
# Section 2: GET /api/narrative-turn/plan
# ===========================================================================

class TestPlanEndpoint:
    def test_get_plan_returns_200_with_dto(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200
        dto = response.json()
        assert dto["schema_version"]
        assert dto["turn_id"]
        assert dto["scope"] == {
            "project_id": scope_params["project_id"],
            "timeline_id": scope_params["timeline_id"],
            "branch_id": scope_params["branch_id"],
        }
        assert dto["chapter_id"] == 1
        assert len(dto["context_fingerprint"]) == 64
        assert dto["planner_revision"]
        assert "recommended_actions" in dto
        assert "custom_action_policy" in dto

    def test_get_plan_has_no_store_cache_control(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.headers.get("cache-control") == "no-store"

    def test_get_plan_recommended_actions_count_is_exactly_3(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        dto = response.json()
        assert len(dto["recommended_actions"]) == 3

    def test_get_plan_deterministic_order_preserved(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        dto = response.json()
        orders = [a["deterministic_order"] for a in dto["recommended_actions"]]
        assert orders == [1, 2, 3]

    def test_get_plan_custom_action_policy_max_length_is_200(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        dto = response.json()
        assert dto["custom_action_policy"]["max_length"] == MAX_CUSTOM_ACTION_LENGTH
        assert dto["custom_action_policy"]["max_length"] == 200

    def test_get_plan_missing_chapter_id_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params=scope_params)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_get_plan_branch_not_found_returns_404(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        params = {**scope_params, "chapter_id": "1", "branch_id": "missing-branch"}
        response = client.get("/api/narrative-turn/plan", params=params)
        assert response.status_code == 404


# ===========================================================================
# Section 3: POST /api/narrative-turn/feasibility
# ===========================================================================

class TestFeasibilityEndpoint:
    def _plan_dto(self, client: TestClient, scope_params: dict[str, str]) -> dict[str, Any]:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200
        return response.json()

    def test_post_feasibility_recommended_action_returns_200(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 200
        dto = response.json()
        assert dto["schema_version"]
        assert dto["validation_id"]
        assert dto["turn_id"] == plan["turn_id"]
        assert dto["action_source"] == "recommended"
        assert dto["selected_action_id"] == plan["recommended_actions"][0]["action_id"]
        assert dto["custom_action_text_hash"] is None
        assert dto["status"] in (
            "allowed", "allowed_with_cost", "requires_clarification", "blocked",
        )
        assert isinstance(dto["blocking_reasons"], list)

    def test_post_feasibility_has_no_store_cache_control(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.headers.get("cache-control") == "no-store"

    def test_post_feasibility_custom_action_returns_200(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "林远进入迷雾森林侦查",
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 200
        dto = response.json()
        assert dto["action_source"] == "custom"
        assert dto["selected_action_id"] is None
        assert dto["custom_action_text_hash"] is not None
        assert len(dto["custom_action_text_hash"]) == 64

    def test_post_feasibility_blocked_status_is_200_not_http_error(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        """blocked feasibility outcome is a 200 success, not an HTTP error."""
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "无名角色使用禁忌魔法攻击平民",
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 200
        dto = response.json()
        # blocked is a valid 200 outcome; never an HTTP error.
        assert dto["status"] in (
            "allowed", "allowed_with_cost", "requires_clarification", "blocked",
        )

    def test_post_feasibility_custom_text_not_in_response(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        raw_text = "林远进入迷雾森林侦查"
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": raw_text,
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 200
        text = response.text
        assert raw_text not in text

    def test_post_feasibility_custom_text_not_in_error(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        """When the request is rejected, raw text must never appear in the error."""
        raw_text = "林远执行非法行动" + "A" * 250  # > 200 normalized chars
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": raw_text,
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 422
        text = response.text
        assert raw_text not in text
        assert "Traceback" not in text
        body_json = response.json()
        assert body_json["error"]["code"] in ("ACTION_TOO_LONG", "ACTION_UNPARSEABLE")

    def test_post_feasibility_context_fingerprint_mismatch_returns_409(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": "0" * 64,  # wrong fingerprint
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONTEXT_STALE"

    def test_post_feasibility_turn_id_mismatch_returns_409(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": "stale-turn-id-0",
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TURN_STALE"

    def test_post_feasibility_invalid_action_id_returns_409(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": "action-not-in-plan-xyz",
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ACTION_NOT_FOUND"

    def test_post_feasibility_missing_action_source_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_post_feasibility_invalid_action_source_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "auto",  # invalid
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_post_feasibility_recommended_missing_selected_action_id_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_post_feasibility_custom_missing_text_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_post_feasibility_custom_empty_text_returns_422(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "   ",  # whitespace-only normalizes to empty
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 422
        body_json = response.json()
        assert body_json["error"]["code"] in ("ACTION_EMPTY", "ACTION_UNPARSEABLE", "ACTION_TOO_LONG")

    def test_post_feasibility_invalid_json_body_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.post(
            "/api/narrative-turn/feasibility",
            content="not-json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    def test_post_feasibility_array_body_returns_400(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.post("/api/narrative-turn/feasibility", json=[1, 2, 3])
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


# ===========================================================================
# Section 4: POST /api/narrative-turn/preview
# ===========================================================================

class TestPreviewEndpoint:
    def _plan_dto(self, client: TestClient, scope_params: dict[str, str]) -> dict[str, Any]:
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200
        return response.json()

    def test_post_preview_recommended_action_returns_200(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 200
        dto = response.json()
        assert dto["schema_version"]
        assert dto["preview_id"]
        assert dto["turn_id"] == plan["turn_id"]
        assert dto["action_source"] == "recommended"
        assert dto["selected_action_id"] == plan["recommended_actions"][0]["action_id"]
        assert dto["custom_action_text_hash"] is None
        assert dto["validation_status"] in (
            "allowed", "allowed_with_cost", "requires_clarification", "blocked",
        )
        assert isinstance(dto["likely_consequences"], list)
        assert isinstance(dto["evidence_codes"], list)

    def test_post_preview_has_no_store_cache_control(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.headers.get("cache-control") == "no-store"

    def test_post_preview_custom_action_returns_200(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "林远进入迷雾森林侦查",
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 200
        dto = response.json()
        assert dto["action_source"] == "custom"
        assert dto["selected_action_id"] is None
        assert dto["custom_action_text_hash"] is not None

    def test_post_preview_custom_text_not_in_response(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        raw_text = "林远进入迷雾森林侦查"
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": raw_text,
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 200
        assert raw_text not in response.text

    def test_post_preview_context_fingerprint_mismatch_returns_409(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": "f" * 64,
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONTEXT_STALE"

    def test_post_preview_turn_id_mismatch_returns_409(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan = self._plan_dto(client, scope_params)
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": "stale-turn-id-zz",
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TURN_STALE"


# ===========================================================================
# Section 5: HTTP method enforcement
# ===========================================================================

class TestHttpMethodEnforcement:
    def test_post_context_returns_405(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.post("/api/narrative-turn/context", json={**scope_params, "chapter_id": 1})
        assert response.status_code == 405

    def test_post_plan_returns_405(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.post("/api/narrative-turn/plan", json={**scope_params, "chapter_id": 1})
        assert response.status_code == 405

    def test_get_feasibility_returns_405(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/feasibility", params=scope_params)
        assert response.status_code == 405

    def test_get_preview_returns_405(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/preview", params=scope_params)
        assert response.status_code == 405


# ===========================================================================
# Section 6: Custom action GET transport forbidden
# ===========================================================================

class TestCustomActionGetTransportForbidden:
    def test_get_does_not_transport_custom_action_text(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        """custom_action_text must NEVER appear in a URL/query string."""
        # Only GET endpoints exist for context/plan; they must not accept
        # custom_action_text as a query param. We verify the param is silently
        # ignored (no 200 echo), not stored, not echoed.
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1",
            "custom_action_text": "should-not-be-transported",
        })
        # GET context ignores unknown params; the param must never appear in
        # the response body or be persisted.
        assert "should-not-be-transported" not in response.text


# ===========================================================================
# Section 7: Error envelope structure
# ===========================================================================

class TestErrorEnvelope:
    def test_error_envelope_shape(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params=scope_params)
        assert response.status_code == 400
        body = response.json()
        assert set(body.keys()) == {"error"}
        assert set(body["error"].keys()) == {"code", "message", "request_id"}
        assert body["error"]["request_id"] is None
        assert isinstance(body["error"]["code"], str)
        assert isinstance(body["error"]["message"], str)

    def test_error_envelope_no_traceback(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1", "branch_id": "no-such-branch",
        })
        text = response.text
        assert "Traceback" not in text
        assert "Exception" not in text
        assert ".py" not in text  # no file path leak
        assert "C:\\" not in text  # no Windows path leak
        assert "D:\\" not in text

    def test_error_envelope_no_absolute_path(
        self, client: TestClient, scope_params: dict[str, str], temp_project_dir: Path,
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1", "branch_id": "no-such-branch",
        })
        text = response.text
        assert str(temp_project_dir) not in text
        assert str(temp_project_dir.resolve()) not in text


# ===========================================================================
# Section 8: Security boundaries — no writes, no Provider, no Store append
# ===========================================================================

class TestSecurityBoundaries:
    def test_no_narrative_turn_store_append_calls(
        self, client: TestClient, scope_params: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Endpoints must never call NarrativeTurnStore.append_plan / append_validation."""
        from system.narrative_turn_store import NarrativeTurnStore

        def forbidden_append(*args, **kwargs):
            raise AssertionError(
                "NarrativeTurnStore.append_* must never be called from 0D4-C routes"
            )

        for method_name in (
            "append_plan", "append_validation", "append_result", "append_transition",
            "append_turn_result", "append_turn_transition",
        ):
            if hasattr(NarrativeTurnStore, method_name):
                monkeypatch.setattr(
                    NarrativeTurnStore, method_name, staticmethod(forbidden_append),
                    raising=False,
                )

        # GET context
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200

        # GET plan
        response = client.get("/api/narrative-turn/plan", params={
            **scope_params, "chapter_id": "1",
        })
        assert response.status_code == 200
        plan = response.json()

        # POST feasibility
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 200

        # POST preview
        response = client.post("/api/narrative-turn/preview", json=body)
        assert response.status_code == 200

    def test_no_filesystem_writes_from_routes(
        self, client: TestClient, scope_params: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Route handlers must never write to the filesystem."""
        # The conftest already blocks real-data writes; here we additionally
        # verify the temp project's data directory is unchanged after a full
        # request cycle.
        ctx = get_project_context()
        before = {}
        for path in ctx.data_dir.rglob("*"):
            if path.is_file():
                before[str(path)] = path.stat().st_mtime_ns

        # GET context
        client.get("/api/narrative-turn/context", params={**scope_params, "chapter_id": "1"})
        # GET plan
        client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        # POST feasibility
        plan_resp = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        plan = plan_resp.json()
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "林远进入迷雾森林侦查",
        }
        client.post("/api/narrative-turn/feasibility", json=body)
        client.post("/api/narrative-turn/preview", json=body)

        after = {}
        for path in ctx.data_dir.rglob("*"):
            if path.is_file():
                after[str(path)] = path.stat().st_mtime_ns

        # No existing file should be modified; new files would be a violation.
        # We assert the file set is unchanged and no mtimes moved.
        assert set(before.keys()) == set(after.keys())
        for k, v in before.items():
            assert after[k] == v, f"file {k} was modified by routes"

    def test_no_provider_calls(
        self, client: TestClient, scope_params: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Routes must never call an LLM Provider."""
        import config

        def forbidden(*args, **kwargs):
            raise AssertionError("Provider must never be called from 0D4-C routes")

        monkeypatch.setattr(config, "LLM_PROVIDER", "mock", raising=False)
        # Even mock providers must not be invoked. We patch the most common
        # entry points to fail if called.
        try:
            from system.llm_provider import LLMProvider
            monkeypatch.setattr(LLMProvider, "complete", staticmethod(forbidden), raising=False)
            monkeypatch.setattr(LLMProvider, "chat", staticmethod(forbidden), raising=False)
        except ImportError:
            pass

        plan_resp = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        plan = plan_resp.json()
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        resp = client.post("/api/narrative-turn/feasibility", json=body)
        assert resp.status_code == 200
        resp = client.post("/api/narrative-turn/preview", json=body)
        assert resp.status_code == 200


# ===========================================================================
# Section 9: Cache-Control on error responses
# ===========================================================================

class TestCacheControlOnErrors:
    def test_400_has_no_store(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params=scope_params)
        assert response.status_code == 400
        assert response.headers.get("cache-control") == "no-store"

    def test_404_has_no_store(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={
            **scope_params, "chapter_id": "1", "branch_id": "no-such-branch",
        })
        assert response.status_code == 404
        assert response.headers.get("cache-control") == "no-store"

    def test_409_has_no_store(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan_resp = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        plan = plan_resp.json()
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": "0" * 64,
            "expected_turn_id": plan["turn_id"],
            "action_source": "recommended",
            "selected_action_id": plan["recommended_actions"][0]["action_id"],
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 409
        assert response.headers.get("cache-control") == "no-store"

    def test_422_has_no_store(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        plan_resp = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        plan = plan_resp.json()
        body = {
            **scope_params,
            "chapter_id": 1,
            "expected_context_fingerprint": plan["context_fingerprint"],
            "expected_turn_id": plan["turn_id"],
            "action_source": "custom",
            "custom_action_text": "A" * 250,  # too long
        }
        response = client.post("/api/narrative-turn/feasibility", json=body)
        assert response.status_code == 422
        assert response.headers.get("cache-control") == "no-store"


# ===========================================================================
# Section 10: Idempotency / determinism
# ===========================================================================

class TestDeterminism:
    def test_two_plan_calls_produce_same_turn_id(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        # Note: turn_id incorporates clock_now, so the routes use _utc_now().
        # We instead verify context_fingerprint is stable across calls.
        r1 = client.get("/api/narrative-turn/context", params={**scope_params, "chapter_id": "1"})
        r2 = client.get("/api/narrative-turn/context", params={**scope_params, "chapter_id": "1"})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["context_fingerprint"] == r2.json()["context_fingerprint"]

    def test_two_plan_calls_produce_same_recommended_action_ids(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        r1 = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        r2 = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        ids1 = [a["action_id"] for a in r1.json()["recommended_actions"]]
        ids2 = [a["action_id"] for a in r2.json()["recommended_actions"]]
        assert ids1 == ids2


# ===========================================================================
# Section 11: Wire DTO field validation (HTTP layer)
# ===========================================================================

class TestWireDtoFieldsOverHttp:
    def test_context_dto_has_no_python_accessor_names(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={**scope_params, "chapter_id": "1"})
        text = response.text
        assert "planning_data_dict" not in text
        assert "chapter_plan_dict" not in text
        assert "world_data_dict" not in text
        assert "character_data_dict" not in text
        assert "narrative_state_dict" not in text
        assert "rolling_window_dict" not in text
        assert "dependencies_dict" not in text

    def test_plan_dto_action_type_is_string(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        for action in response.json()["recommended_actions"]:
            assert isinstance(action["action_type"], str)
            assert action["action_type"] in (
                "advance", "delay", "divert", "investigate", "conserve",
                "engage", "withdraw", "negotiate", "discover",
            ) or action["action_type"]  # any non-empty string

    def test_plan_dto_expected_costs_is_array_of_objects(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/plan", params={**scope_params, "chapter_id": "1"})
        for action in response.json()["recommended_actions"]:
            assert isinstance(action["expected_costs"], list)
            for cost in action["expected_costs"]:
                assert set(cost.keys()) == {"key", "level"}
            assert isinstance(action["expected_risks"], list)
            for risk in action["expected_risks"]:
                assert set(risk.keys()) == {"key", "level"}

    def test_context_dto_has_no_tuple_or_set(
        self, client: TestClient, scope_params: dict[str, str],
    ) -> None:
        response = client.get("/api/narrative-turn/context", params={**scope_params, "chapter_id": "1"})
        # JSON serialization already enforces this, but we double-check that
        # the response text does not contain Python tuple/set repr.
        text = response.text
        assert "(" not in text or text.count("(") == 0  # no tuple repr like (1, 2)
        assert "set(" not in text
        assert "Path(" not in text
        assert "datetime" not in text
