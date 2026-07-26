"""Isolated safety tests for 0D3C2-A; no real provider or network is allowed."""
from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from core.contracts.model_persona_execution import ExecutionProfile, GenerationParameters, StructuredOutputMode
from core.project_context import get_project_context
from system.live_panel_execution_service import LivePanelExecutionService
from system.model_persona_execution_service import ProviderRequest, ProviderResponse


def _context(tmp_path: Path):
    root = tmp_path / "isolated-live-hardening"
    for relative in ("data/drafts", "data/versions", "data/planning"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "data/state.json").write_text(json.dumps({"project_id": "hardening-project", "timeline_id": "main", "current_chapter": 1}), encoding="utf-8")
    (root / "data/story_spec.json").write_text("{}", encoding="utf-8")
    (root / "data/planning/planning.json").write_text(json.dumps({"chapters": [{"chapter_number": 1, "chapter_goal": "goal", "pacing_design": {}}]}), encoding="utf-8")
    draft = root / "data/drafts/chapter_001_draft_v001.json"
    draft.write_text(json.dumps({"chapter_id": 1, "chapter_title": "One", "draft_text": "A bounded test chapter with a decision.", "version": 1}), encoding="utf-8")
    (root / "data/versions/chapter_001_versions.json").write_text(json.dumps({"drafts": [{"source_type": "draft", "version": 1, "json_path": str(draft)}], "edited": [], "manual": [], "selected": {}}), encoding="utf-8")
    return get_project_context(root)


class _NoNetworkProvider:
    provider_id = "fake-live-provider"
    model_id = "fake-live-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(json.dumps({"reader_reaction": "ok", "strengths": [], "concerns": [], "reader_questions": [], "optimization_directions": [], "overall_impression": "ok"}), usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    def count_input_tokens(self, system_prompt: str, user_prompt: str) -> int:
        return 1


class _SecretFailingProvider(_NoNetworkProvider):
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise RuntimeError("adapter-secret-sentinel-must-not-persist")


class _SourceMutatingProvider(_NoNetworkProvider):
    def __init__(self, draft_path: Path) -> None:
        super().__init__()
        self.draft_path = draft_path

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        response = super().generate(request)
        if self.calls == 1:
            payload = json.loads(self.draft_path.read_text(encoding="utf-8"))
            payload["draft_text"] = "Changed during sequential execution."
            self.draft_path.write_text(json.dumps(payload), encoding="utf-8")
        return response


def _profile(version: str = "1.0") -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="live-test", profile_version=version, provider_type="openai_compatible",
        provider_id="fake-live-provider", model_id="fake-live-model", enabled=True,
        structured_output_mode=StructuredOutputMode.JSON,
        generation_parameters=GenerationParameters(max_output_tokens=64, timeout_seconds=12), timeout_seconds=12,
        endpoint_identity="hidden-endpoint-identity",
    )


def _service(tmp_path: Path, provider=None, version: str = "1.0") -> LivePanelExecutionService:
    return LivePanelExecutionService(_context(tmp_path), provider=provider or _NoNetworkProvider(), profiles={"live-test": _profile(version)})


def _ticket(service: LivePanelExecutionService):
    ticket, error = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1,
        source_version_id=None, persona_ids=["hook_driven_reader"], profile_id="live-test",
        requested_max_provider_calls=1, consent_text_version="live-consent-v1",
    )
    assert error is None and ticket is not None
    return ticket


def test_consent_is_server_owned_safe_and_creates_no_provider_or_run(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    public_profiles = service.list_public_profiles()
    serialized = json.dumps(ticket.to_dict()) + json.dumps(public_profiles)
    assert provider.calls == 0
    assert ticket.status.value == "issued" and ticket.token_budget.cost_estimate_available is False
    assert ticket.token_budget.max_estimated_cost is None and ticket.token_budget.retry_policy == "0"
    assert ticket.token_budget.max_input_tokens == 4096 and ticket.token_budget.max_total_tokens == 4160
    assert public_profiles[0]["ready_for_consent"] is True
    assert public_profiles[0]["token_counter_available"] is True
    assert public_profiles[0]["cost_estimate_available"] is False
    assert public_profiles[0]["max_input_tokens"] == 20480
    assert "endpoint" not in serialized and "api_key" not in serialized and "hidden-endpoint" not in serialized
    context = service.context
    assert not (context.data_dir / "simulator" / "model_persona_panel_runs").exists()


def test_ticket_execution_is_idempotent_and_response_loss_is_recoverable(tmp_path: Path, monkeypatch):
    def _no_socket(*args, **kwargs):
        raise AssertionError("Live hardening test attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", _no_socket)
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    first = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    second = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    recovered = service.recover(ticket.ticket_id, ticket.idempotency_key)
    assert provider.calls == 1
    assert first["status"] == second["status"] == recovered["status"] == "completed"
    assert first["panel_execution_id"] == second["panel_execution_id"] == recovered["panel_execution_id"]


def test_concurrent_duplicate_has_exactly_one_owner_and_provider_call(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _unused: service.execute_ticket(ticket.ticket_id, ticket.idempotency_key), range(2)))
    recovered = service.recover(ticket.ticket_id, ticket.idempotency_key)
    assert provider.calls == 1
    assert {item["status"] for item in outcomes}.issubset({"in_progress", "completed"})
    assert recovered["status"] == "completed" and recovered["panel_execution_id"]


def test_expired_or_changed_ticket_cannot_call_provider(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    expired = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1, source_version_id=None,
        persona_ids=["hook_driven_reader"], profile_id="live-test", requested_max_provider_calls=1,
        consent_text_version="live-consent-v1", now=ticket.issued_at - timedelta(minutes=10),
    )[0]
    assert expired is not None
    assert service.execute_ticket(expired.ticket_id, expired.idempotency_key)["safe_error_code"] == "LIVE_CONSENT_EXPIRED"
    service.panel.child_service._profiles["live-test"] = _profile("2.0")
    assert service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)["safe_error_code"] == "PROFILE_REGISTRY_CHANGED"
    assert provider.calls == 0


def test_source_changed_after_consent_blocks_before_provider(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    draft = service.context.data_dir / "drafts" / "chapter_001_draft_v001.json"
    payload = json.loads(draft.read_text(encoding="utf-8"))
    payload["draft_text"] = "Changed after consent."
    draft.write_text(json.dumps(payload), encoding="utf-8")
    result = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert result["status"] == "blocked"
    assert result["safe_error_code"] == "SOURCE_CHANGED_AFTER_CONSENT"
    assert provider.calls == 0


def test_source_change_during_sequential_execution_never_starts_a_second_child_call(tmp_path: Path):
    context = _context(tmp_path)
    draft = context.data_dir / "drafts" / "chapter_001_draft_v001.json"
    provider = _SourceMutatingProvider(draft)
    service = LivePanelExecutionService(context, provider=provider, profiles={"live-test": _profile()})
    ticket, error = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1, source_version_id=None,
        persona_ids=["hook_driven_reader", "character_empathy_reader"], profile_id="live-test",
        requested_max_provider_calls=2, consent_text_version="live-consent-v1",
    )
    assert error is None and ticket is not None
    result = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert provider.calls == 1
    assert result["status"] == "partially_completed"
    assert result["safe_error_code"] == "SOURCE_CHANGED_AFTER_CONSENT"


def test_budget_and_redaction_safety(tmp_path: Path):
    provider = _SecretFailingProvider()
    service = _service(tmp_path, provider)
    rejected, error = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1, source_version_id=None,
        persona_ids=["hook_driven_reader"], profile_id="live-test", requested_max_provider_calls=6,
        consent_text_version="live-consent-v1",
    )
    assert rejected is None and error == "MAX_CALLS_EXCEEDS_POLICY"
    ticket = _ticket(service)
    result = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in service.context.data_dir.rglob("*.json"))
    assert result["status"] == "failed" and provider.calls == 1
    assert "adapter-secret-sentinel" not in persisted
    assert "hidden-endpoint" not in persisted


def test_stale_in_progress_is_reconciliation_required_without_retry(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    owner, record = service.store.reserve(ticket)
    assert owner and record["status"] == "in_progress"
    record["updated_at"] = (ticket.issued_at - timedelta(minutes=10)).isoformat()
    path = service.store.ownership_dir / f"{ticket.ticket_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    result = service.recover(ticket.ticket_id, ticket.idempotency_key)
    assert result["status"] == "reconciliation_required"
    assert provider.calls == 0


def test_cancel_before_execution_prevents_provider_call(tmp_path: Path):
    provider = _NoNetworkProvider()
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    cancelled = service.request_cancellation(ticket.ticket_id, ticket.idempotency_key)
    replay = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert cancelled["status"] == replay["status"] == "cancelled"
    assert provider.calls == 0
