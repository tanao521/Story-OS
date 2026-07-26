"""Read-only safety evidence for the controlled-live preflight.

These tests use an isolated temporary project and an injected in-process fake
provider.  They must never read credentials or contact an external network.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

from core.contracts.model_persona_execution import ExecutionMode, ExecutionProfile
from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest
from core.project_context import get_project_context
from system.model_persona_execution_service import ProviderRequest, ProviderResponse
from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService


def _context(tmp_path: Path):
    root = tmp_path / "isolated-live-preflight"
    for relative in ("data/drafts", "data/versions", "data/planning"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "data/state.json").write_text(json.dumps({"project_id": "preflight-project", "timeline_id": "main", "current_chapter": 1}), encoding="utf-8")
    (root / "data/story_spec.json").write_text("{}", encoding="utf-8")
    (root / "data/planning/planning.json").write_text(json.dumps({"chapters": [{"chapter_number": 1, "chapter_goal": "goal", "pacing_design": {}}]}), encoding="utf-8")
    draft = root / "data/drafts/chapter_001_draft_v001.json"
    draft.write_text(json.dumps({"chapter_id": 1, "chapter_title": "One", "draft_text": "A bounded test chapter with a decision.", "version": 1}), encoding="utf-8")
    (root / "data/versions/chapter_001_versions.json").write_text(json.dumps({"drafts": [{"source_type": "draft", "version": 1, "json_path": str(draft)}], "edited": [], "manual": [], "selected": {}}), encoding="utf-8")
    return get_project_context(root)


class _NoNetworkProvider:
    provider_id = "fake-preflight"
    model_id = "fake-preflight-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(json.dumps({"reader_reaction": "ok", "strengths": [], "concerns": [], "reader_questions": [], "optimization_directions": [], "overall_impression": "ok"}), usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


class _FailingProvider(_NoNetworkProvider):
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise RuntimeError("provider diagnostic with secret-sentinel=never-persist")


def _live_request(**changes):
    values = {"project_id": "preflight-project", "timeline_id": "main", "chapter_id": 1, "persona_ids": ["hook_driven_reader"], "execution_mode": ExecutionMode.LIVE, "execution_profile": "default", "allow_model_call": True, "max_provider_calls": 1}
    values.update(changes)
    return ModelPersonaPanelExecutionRequest(**values)


def test_live_gate_rejects_missing_or_false_allow_before_fake_provider_call(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = ModelPersonaPanelExecutionService(_context(tmp_path), provider=provider)
    for allowed in (False,):
        result = service.execute(_live_request(allow_model_call=allowed))
        assert result.status.value == "blocked"
        assert result.error_code == "MODEL_CALL_BLOCKED"
    assert provider.calls == 0


def test_live_plan_is_read_only_and_unknown_profile_is_rejected(tmp_path: Path):
    context, provider = _context(tmp_path), _NoNetworkProvider()
    service = ModelPersonaPanelExecutionService(context, provider=provider)
    before = sorted(path.relative_to(context.root).as_posix() for path in context.data_dir.rglob("*.json"))
    plan = service.plan(_live_request(execution_profile="unknown"))
    after = sorted(path.relative_to(context.root).as_posix() for path in context.data_dir.rglob("*.json"))
    assert not plan.can_execute and plan.error_code == "INVALID_PROFILE"
    assert provider.calls == 0 and before == after


def test_live_disabled_or_unconfigured_profile_is_safely_blocked(tmp_path: Path):
    context = _context(tmp_path)
    disabled = ExecutionProfile(profile_id="disabled-live", provider_type="openai_compatible", provider_id="allowed", model_id="allowed-model", enabled=False)
    service = ModelPersonaPanelExecutionService(context, profiles={"disabled-live": disabled})
    plan = service.plan(_live_request(execution_profile="disabled-live"))
    assert not plan.can_execute and plan.error_code == "PROVIDER_NOT_CONFIGURED"


def test_live_persona_and_budget_limits_are_hard_gates(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = ModelPersonaPanelExecutionService(_context(tmp_path), provider=provider)
    too_many = service.plan(_live_request(persona_ids=["hook_driven_reader"] * 6, max_provider_calls=5))
    no_personas = service.plan(_live_request(persona_ids=[], max_provider_calls=1))
    over_budget = service.plan(_live_request(max_provider_calls=6))
    assert {too_many.error_code, no_personas.error_code, over_budget.error_code} >= {"PERSONA_LIMIT_EXCEEDED", "INVALID_PERSONA_SELECTION", "PANEL_CALL_BUDGET_EXCEEDED"}
    assert provider.calls == 0


def test_preflight_exposes_missing_idempotency_when_force_repeats_live_execution(tmp_path: Path):
    """Evidence of a blocker: force permits distinct live executions for the same scope."""
    provider = _NoNetworkProvider()
    service = ModelPersonaPanelExecutionService(_context(tmp_path), provider=provider)
    first = service.execute(_live_request(force=True))
    second = service.execute(_live_request(force=True))
    assert first.status.value == second.status.value == "completed"
    assert first.panel_execution_id != second.panel_execution_id
    assert provider.calls == 2
    assert first.actual_provider_call_count == second.actual_provider_call_count == 1


def test_fake_live_execution_has_a_network_canary(tmp_path: Path, monkeypatch):
    """The injected provider path remains local even when socket creation is forbidden."""
    def _forbidden_socket(*args, **kwargs):
        raise AssertionError("preflight test attempted network access")

    monkeypatch.setattr(socket, "create_connection", _forbidden_socket)
    provider = _NoNetworkProvider()
    result = ModelPersonaPanelExecutionService(_context(tmp_path), provider=provider).execute(_live_request())
    assert result.status.value == "completed"
    assert provider.calls == 1


def test_provider_exception_is_reduced_to_a_safe_persisted_error(tmp_path: Path):
    context = _context(tmp_path)
    result = ModelPersonaPanelExecutionService(context, provider=_FailingProvider()).execute(_live_request())
    stored_text = "\n".join(path.read_text(encoding="utf-8") for path in context.data_dir.rglob("*.json"))
    assert result.status.value == "failed"
    assert result.error_code == "PROVIDER_ERROR"
    assert "secret-sentinel" not in stored_text
    assert "Provider request failed" in stored_text
