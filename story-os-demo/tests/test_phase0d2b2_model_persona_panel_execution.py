"""Focused regression tests for bounded multi-persona model execution."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from core.contracts.model_persona_execution import ExecutionMode
from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest
from core.project_context import get_project_context
from system.model_persona_execution_service import ProviderRequest, ProviderResponse
from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService


def _project(tmp_path: Path):
    root = tmp_path / "panel-project"
    for relative in ("data/drafts", "data/edited", "data/manual", "data/versions", "data/summaries", "data/planning"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "data/state.json").write_text(json.dumps({"project_id": "panel-project", "timeline_id": "main", "current_chapter": 1}), encoding="utf-8")
    (root / "data/story_spec.json").write_text("{}", encoding="utf-8")
    (root / "data/planning/planning.json").write_text(json.dumps({"chapters": [{"chapter_number": 1, "chapter_goal": "goal", "pacing_design": {}}]}), encoding="utf-8")
    content = "Opening tension. The protagonist discovers a threat and must decide what to do."
    draft = root / "data/drafts/chapter_001_draft_v001.json"
    draft.write_text(json.dumps({"chapter_id": 1, "chapter_title": "One", "draft_text": content, "version": 1, "created_at": datetime.now().isoformat()}), encoding="utf-8")
    (root / "data/versions/chapter_001_versions.json").write_text(json.dumps({"drafts": [{"source_type": "draft", "version": 1, "json_path": str(draft), "chapter_title": "One"}], "edited": [], "manual": [], "selected": {}}), encoding="utf-8")
    return get_project_context(root)


class _Provider:
    provider_id = "fake"
    model_id = "fake-model"
    def __init__(self, outcomes=None, usage=True): self.calls, self.outcomes, self.usage = 0, list(outcomes or []), usage
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, Exception): raise outcome
        if outcome == "invalid": return ProviderResponse("not-json", usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        return ProviderResponse(json.dumps({"reader_reaction": "Useful response", "strengths": [], "concerns": [], "reader_questions": [], "optimization_directions": [], "overall_impression": "Fine"}), usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15} if self.usage else None)


def _request(personas, **kwargs):
    values = {"execution_mode": ExecutionMode.LIVE, "allow_model_call": True, "max_provider_calls": 3}
    values.update(kwargs)
    return ModelPersonaPanelExecutionRequest(project_id="panel-project", timeline_id="main", chapter_id=1, persona_ids=personas, **values)


def test_plan_is_read_only_orders_authoritatively_and_rejects_budget(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider()
    service = ModelPersonaPanelExecutionService(ctx, provider=provider)
    before = list((ctx.root / "data").rglob("*.json"))
    plan = service.plan(_request(["world_logic_reader", "character_empathy_reader", "hook_driven_reader"], max_provider_calls=2))
    assert plan.ordered_persona_ids == sorted(plan.ordered_persona_ids)
    assert not plan.can_execute and plan.error_code == "PANEL_CALL_BUDGET_EXCEEDED"
    assert provider.calls == 0
    assert list((ctx.root / "data").rglob("*.json")) == before
    assert not (ctx.root / "data/simulator/model_persona_panel_runs").exists()


def test_three_live_misses_are_sequentially_bounded_and_audited(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider()
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_request(["hook_driven_reader", "character_empathy_reader", "world_logic_reader"]))
    assert result.status.value == "completed"
    assert provider.calls == result.actual_provider_call_count == result.expected_provider_call_count == 3
    assert result.usage.total_tokens == 45 and result.usage_completeness == "complete"
    stored = ctx.root / "data/simulator/model_persona_panel_runs" / f"{result.panel_execution_id}.json"
    text = stored.read_text(encoding="utf-8")
    assert "system_prompt" not in text and "draft_text" not in text and "api_key" not in text


def test_budget_blocked_before_any_provider_call(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider()
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_request(["hook_driven_reader", "character_empathy_reader", "world_logic_reader"], max_provider_calls=2))
    assert result.status.value == "blocked" and result.error_code == "PANEL_CALL_BUDGET_EXCEEDED"
    assert provider.calls == result.actual_provider_call_count == 0


def test_cache_hits_use_no_new_live_provider_calls(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider()
    service = ModelPersonaPanelExecutionService(ctx, provider=provider)
    request = _request(["hook_driven_reader", "character_empathy_reader"])
    service.execute(request)
    second = service.execute(request)
    assert provider.calls == 2
    assert second.cache_hit_count == 2 and second.actual_provider_call_count == 0
    assert second.usage is None and second.usage_completeness == "not_applicable"


def test_no_retry_and_partial_completion_preserves_success(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider(["ok", RuntimeError("network failure")])
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_request(["hook_driven_reader", "world_logic_reader"], max_provider_calls=2))
    assert provider.calls == 2
    assert result.status.value == "partially_completed"
    assert set(result.child_statuses.values()) == {"completed", "failed"}


def test_all_invalid_outputs_have_stable_invalid_status(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider(["invalid", "invalid"])
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_request(["hook_driven_reader", "world_logic_reader"], max_provider_calls=2))
    assert provider.calls == 2 and result.status.value == "invalid_output"


@pytest.mark.parametrize("personas", [[], ["hook_driven_reader", "hook_driven_reader"], ["unknown"], ["hook_driven_reader"] * 6])
def test_invalid_persona_selections_are_blocked_without_call(tmp_path: Path, personas):
    ctx, provider = _project(tmp_path), _Provider()
    request = _request(personas, max_provider_calls=5)
    plan = ModelPersonaPanelExecutionService(ctx, provider=provider).plan(request)
    assert not plan.can_execute and provider.calls == 0


def test_staleness_is_read_only_and_detects_source_change(tmp_path: Path):
    ctx, provider = _project(tmp_path), _Provider()
    service = ModelPersonaPanelExecutionService(ctx, provider=provider)
    result = service.execute(_request(["hook_driven_reader"]))
    draft = next((ctx.root / "data/drafts").glob("*.json"))
    payload = json.loads(draft.read_text(encoding="utf-8")); payload["draft_text"] += " changed"
    draft.write_text(json.dumps(payload), encoding="utf-8")
    assert service.check_staleness(result.panel_execution_id).value == "stale"
    assert provider.calls == 1


def test_cli_plan_and_mock_run_windows_subprocess(tmp_path: Path):
    ctx = _project(tmp_path)
    root = Path(__file__).resolve().parents[1]
    plan = subprocess.run([sys.executable, "main.py", "plan-reader-persona-model-panel", "--chapter", "1", "--persona", "world_logic_reader", "--persona", "hook_driven_reader", "--project-root", str(ctx.root)], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert plan.returncode == 0 and "expected_provider_calls" in plan.stdout
    run = subprocess.run([sys.executable, "main.py", "run-reader-persona-model-panel", "--chapter", "1", "--persona", "hook_driven_reader", "--mode", "mock", "--project-root", str(ctx.root)], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0 and "actual_provider_call_count" in run.stdout


def test_web_plan_run_list_and_budget_error(tmp_path: Path):
    from fastapi.testclient import TestClient
    from web.app import app
    ctx = _project(tmp_path)
    client = TestClient(app)
    body = {"project_root": str(ctx.root), "chapter_id": 1, "persona_ids": ["world_logic_reader", "hook_driven_reader"], "mode": "mock"}
    plan = client.post("/api/reader-persona/model-panel/plan", json=body)
    assert plan.status_code == 200 and plan.json()["result"]["expected_provider_calls"] == 0
    run = client.post("/api/reader-persona/model-panel/runs", json=body)
    assert run.status_code == 200
    execution_id = run.json()["result"]["panel_execution_id"]
    detail = client.get(f"/api/reader-persona/model-panel/runs/{execution_id}", params={"project_root": str(ctx.root)})
    assert detail.status_code == 200 and "system_prompt" not in detail.text
    budget = client.post("/api/reader-persona/model-panel/runs", json={**body, "mode": "live", "allow_model_call": True, "max_provider_calls": 0})
    assert budget.status_code in {400, 503}
