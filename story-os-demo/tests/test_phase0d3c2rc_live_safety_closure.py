"""RC safety matrix using only in-process providers and temporary projects."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from system.live_panel_execution_service import live_execution_ui_enabled, public_live_capability
from system.model_persona_execution_service import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)
from test_phase0d3c2a_live_hardening import _NoNetworkProvider, _service, _ticket


VALID = {
    "reader_reaction": "bounded reaction",
    "strengths": [],
    "concerns": [],
    "reader_questions": [],
    "optimization_directions": [],
    "overall_impression": "bounded impression",
}
SENTINELS = (
    "secret-key-sentinel",
    "endpoint-sentinel",
    "prompt-sentinel",
    "chapter-sentinel",
    "exception-sentinel",
    "path-sentinel",
)


class MatrixProvider(_NoNetworkProvider):
    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = list(outcomes)

    def generate(self, request):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        text, usage = outcome
        return ProviderResponse(text, usage=usage)


def _valid(usage=None):
    if usage is ...:
        usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    return json.dumps(VALID), usage


def _execute(tmp_path: Path, provider: MatrixProvider, personas=None):
    service = _service(tmp_path, provider)
    ticket = _ticket(service)
    if personas:
        ticket, error = service.issue_consent(
            project_id="hardening-project", timeline_id="main", chapter_id=1,
            source_version_id=None, persona_ids=personas, profile_id="live-test",
            requested_max_provider_calls=len(personas), consent_text_version="live-consent-v1",
        )
        assert error is None and ticket is not None
    return service, ticket, service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)


@pytest.fixture(autouse=True)
def no_network_or_live_capability(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("RC attempted network access")

    monkeypatch.delenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", raising=False)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProviderTimeoutError("exception-sentinel timeout"), "PROVIDER_TIMEOUT"),
        (ProviderRateLimitError("exception-sentinel rate"), "PROVIDER_RATE_LIMITED"),
        (ProviderAuthError("secret-key-sentinel endpoint-sentinel"), "PROVIDER_AUTH_ERROR"),
        (RuntimeError("exception-sentinel path-sentinel"), "PROVIDER_ERROR"),
    ],
)
def test_provider_failures_are_single_call_safe_and_redacted(tmp_path: Path, error, code):
    provider = MatrixProvider([error])
    service, ticket, result = _execute(tmp_path, provider)
    assert provider.calls == 1
    assert result["status"] == "failed"
    assert result["safe_error_code"] == code
    assert result["actual_provider_calls"] == 1
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in service.context.data_dir.rglob("*.json"))
    for sentinel in SENTINELS:
        assert sentinel not in persisted
    replay = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert replay["panel_execution_id"] == result["panel_execution_id"]
    assert provider.calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        "not-json prompt-sentinel",
        json.dumps({"overall_impression": "schema missing required reaction"}),
        json.dumps({**VALID, "concerns": [{"message": "unsupported", "evidence_refs": ["missing-ref"]}]}),
    ],
)
def test_invalid_json_schema_and_grounding_never_complete_or_persist_raw(tmp_path: Path, payload: str):
    provider = MatrixProvider([(payload, None)])
    service, _, result = _execute(tmp_path, provider)
    assert provider.calls == 1
    assert result["status"] == "failed"
    assert result["safe_error_code"] == "MODEL_OUTPUT_INVALID"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in service.context.data_dir.rglob("*.json"))
    assert payload not in persisted
    assert "prompt-sentinel" not in persisted


def test_partial_success_preserves_child_results_without_retry(tmp_path: Path):
    provider = MatrixProvider([_valid(...), ProviderTimeoutError("exception-sentinel")])
    service, _, result = _execute(
        tmp_path, provider, ["hook_driven_reader", "character_empathy_reader"]
    )
    assert provider.calls == 2
    assert result["status"] == "partially_completed"
    assert result["actual_provider_calls"] == 2
    assert result["usage_completeness"] == "partial"
    panel = service.panel.get_run(result["panel_execution_id"])
    assert panel is not None
    assert sorted(panel.child_statuses.values()) == ["completed", "failed"]
    children = [service.panel.child_service.get_run(run_id) for run_id in panel.child_execution_ids.values()]
    assert {child.error_code for child in children} == {None, "PROVIDER_TIMEOUT"}


def test_all_failure_and_missing_or_partial_usage_are_honest(tmp_path: Path):
    failed_provider = MatrixProvider([
        ProviderRateLimitError("exception-sentinel"),
        ProviderAuthError("secret-key-sentinel"),
    ])
    service, _, failed = _execute(
        tmp_path / "failed", failed_provider, ["hook_driven_reader", "character_empathy_reader"]
    )
    assert failed_provider.calls == 2 and failed["status"] == "failed"
    panel = service.panel.get_run(failed["panel_execution_id"])
    assert panel is not None and panel.usage_completeness == "partial"
    assert panel.usage is not None
    assert panel.usage.input_tokens is None and panel.usage.output_tokens is None
    assert panel.usage.total_tokens is None

    missing = MatrixProvider([_valid(None)])
    missing_service, _, missing_result = _execute(tmp_path / "missing", missing)
    missing_panel = missing_service.panel.get_run(missing_result["panel_execution_id"])
    assert missing_panel is not None and missing_panel.usage_completeness == "partial"
    assert missing_panel.usage is not None
    assert missing_panel.usage.input_tokens is None
    assert missing_panel.usage.output_tokens is None
    assert missing_panel.usage.total_tokens is None

    partial = MatrixProvider([_valid({"input_tokens": 3})])
    partial_service, _, partial_result = _execute(tmp_path / "partial", partial)
    partial_panel = partial_service.panel.get_run(partial_result["panel_execution_id"])
    assert partial_panel is not None and partial_panel.usage_completeness == "partial"
    assert partial_panel.usage.input_tokens == 3
    assert partial_panel.usage.output_tokens is None and partial_panel.usage.total_tokens is None


@pytest.mark.parametrize("value", [None, "", "0", "false", "FALSE", "off", "no", "random"])
def test_production_capability_is_default_off(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", raising=False)
    else:
        monkeypatch.setenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", value)
    assert live_execution_ui_enabled() is False
    assert public_live_capability() == {
        "enabled": False,
        "status": "disabled",
        "safe_error_code": "LIVE_EXECUTION_DISABLED",
    }


def test_capability_enablement_is_explicit_and_test_scoped(monkeypatch):
    monkeypatch.setenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", "true")
    assert live_execution_ui_enabled() is True
    assert public_live_capability()["enabled"] is True
