"""0D3C3 offline readiness, canonical envelope, and exact-counter seams."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from core.contracts.model_persona_execution import GenerationParameters
from system.live_panel_execution_service import LivePanelExecutionService
from system.model_persona_execution_service import ProviderRequest, ProviderResponse
from system.model_persona_provider_openai import OpenAICompatibleModelPersonaProvider
from system.provider_operational_readiness import (
    ProviderOperationalReadiness,
    ProviderTokenCounterRegistry,
    prepare_live_request_dry_run,
    request_fingerprint,
)
from test_phase0d3c2a_live_hardening import _context, _profile


ROOT = Path(__file__).resolve().parents[1]
LIVE_MODULE = (ROOT / "web" / "static" / "simulator-live-consent.js").read_text(encoding="utf-8")


class FixtureJsonByteCounter:
    """Exact counter for the fixture provider's canonical UTF-8 JSON protocol."""

    counter_id = "fixture-json-utf8"
    counter_revision = "1.0.0"

    def supports(self, *, provider_id: str, model_id: str) -> bool:
        return provider_id == "fixture-provider" and model_id == "fixture-chat-v1"

    def count_request_tokens(self, request: ProviderRequest) -> int:
        encoded = json.dumps(
            request.canonical_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return len(encoded)


def _request(system="", user="short", schema=None):
    return ProviderRequest(
        "fixture-chat-v1", system, user, GenerationParameters(max_output_tokens=64),
        provider_id="fixture-provider", profile_revision="fixture-profile-1",
        structured_output_schema=schema, counter_id="fixture-json-utf8",
        counter_revision="1.0.0",
    )


@pytest.fixture(autouse=True)
def no_network_or_capability(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("0D3C3 attempted network access")

    monkeypatch.delenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", raising=False)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.mark.parametrize(
    ("system", "user"),
    [
        ("", "short"),
        ("系统", "中文内容。"),
        ("System", "English punctuation!\nSecond line."),
        ("Persona 读者", "Mixed 中英 Unicode 😀"),
        ("Reader persona", "chapter " * 300),
    ],
)
def test_fixture_counter_is_deterministic_for_golden_inputs(system, user):
    counter = FixtureJsonByteCounter()
    request = _request(system, user)
    first = counter.count_request_tokens(request)
    assert first == counter.count_request_tokens(request)
    assert first == len(json.dumps(request.canonical_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def test_registry_blocks_unknown_model_without_fallback():
    registry = ProviderTokenCounterRegistry([FixtureJsonByteCounter()])
    assert registry.resolve(provider_id="fixture-provider", model_id="fixture-chat-v1") is not None
    assert registry.resolve(provider_id="fixture-provider", model_id="unknown-model") is None
    result = prepare_live_request_dry_run(
        request=ProviderRequest("unknown-model", "s", "u", GenerationParameters(), provider_id="fixture-provider"),
        counter=None,
        max_input_tokens=4096,
    )
    assert result["ready"] is False
    assert result["safe_readiness_code"] == "MODEL_TOKENIZER_UNSUPPORTED"
    assert result["input_tokens"] is None


def test_canonical_envelope_fingerprint_binds_prompt_schema_and_counter_revision():
    base = _request("system", "user")
    same = _request("system", "user")
    changed_prompt = _request("system", "user changed")
    changed_schema = _request("system", "user", {"type": "json_schema", "json_schema": {"name": "feedback"}})
    changed_counter = ProviderRequest(
        "fixture-chat-v1", "system", "user", GenerationParameters(max_output_tokens=64),
        provider_id="fixture-provider", profile_revision="fixture-profile-1",
        counter_id="fixture-json-utf8", counter_revision="2.0.0",
    )
    assert request_fingerprint(base) == request_fingerprint(same)
    assert len({request_fingerprint(base), request_fingerprint(changed_prompt), request_fingerprint(changed_schema), request_fingerprint(changed_counter)}) == 4


def test_adapter_sends_the_exact_canonical_payload_without_network():
    observed = {}

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{}"}}]}

    def post(url, **kwargs):
        observed.update(kwargs)
        return Response()

    adapter = OpenAICompatibleModelPersonaProvider(
        provider_id="fixture-provider", model_id="fixture-chat-v1",
        api_key="secret-tokenizer-sentinel", base_url="https://endpoint-tokenizer-sentinel.invalid", post=post,
    )
    request = _request("system", "user", {"type": "json_object"})
    adapter.generate(request)
    assert observed["json"] == request.canonical_payload()
    serialized = json.dumps(observed["json"])
    assert "secret-tokenizer-sentinel" not in serialized
    assert "endpoint-tokenizer-sentinel" not in serialized


def test_offline_dry_run_counts_or_blocks_without_provider_call():
    request = _request("system", "中文 and English")
    counter = FixtureJsonByteCounter()
    count = counter.count_request_tokens(request)
    ready = prepare_live_request_dry_run(request=request, counter=counter, max_input_tokens=count)
    blocked = prepare_live_request_dry_run(request=request, counter=counter, max_input_tokens=count - 1)
    assert ready["ready"] is True and ready["input_tokens"] == count
    assert blocked["ready"] is False and blocked["safe_readiness_code"] == "INPUT_TOKEN_BUDGET_EXCEEDED"

    class BrokenCounter(FixtureJsonByteCounter):
        def count_request_tokens(self, request):
            raise RuntimeError("secret-tokenizer-sentinel")

    unavailable = prepare_live_request_dry_run(
        request=request, counter=BrokenCounter(), max_input_tokens=4096
    )
    assert unavailable["ready"] is False
    assert unavailable["safe_readiness_code"] == "INPUT_TOKEN_BUDGET_UNAVAILABLE"
    assert "secret-tokenizer-sentinel" not in json.dumps(unavailable)


def test_public_readiness_excludes_credentials_endpoint_prompt_and_path():
    readiness = ProviderOperationalReadiness(
        profile_id="fixture", profile_revision="1", provider_label="Fixture",
        model_label="fixture-chat-v1", enabled=True, credential_configured=True,
        exact_token_counter_available=True, counter_id="fixture-json-utf8",
        counter_revision="1.0.0", request_serialization_supported=True,
        budget_policy_supported=True, structured_output_supported=True,
        live_capability_default_off=True, ready_for_consent=True,
        ready_for_live_execution=False, safe_readiness_code="PROFILE_READY_CAPABILITY_DISABLED",
    )
    public = readiness.to_public_dict()
    serialized = json.dumps(public)
    for forbidden in ("credential_configured", "secret-tokenizer-sentinel", "endpoint-tokenizer-sentinel", "prompt-tokenizer-sentinel", "path-tokenizer-sentinel"):
        assert forbidden not in serialized
    assert public["ready_for_consent"] is True
    assert public["ready_for_live_execution"] is False


def test_over_budget_blocks_before_generate_and_reports_zero_actual_calls(tmp_path: Path):
    class OverBudgetProvider:
        provider_id = "fake-live-provider"
        model_id = "fake-live-model"
        counter_id = "fixture-over-budget"
        counter_revision = "1"

        def __init__(self):
            self.calls = 0

        def count_request_tokens(self, request):
            return 4097

        def generate(self, request):
            self.calls += 1
            return ProviderResponse("{}")

    provider = OverBudgetProvider()
    service = LivePanelExecutionService(
        _context(tmp_path), provider=provider, profiles={"live-test": _profile()}
    )
    ticket, error = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1,
        source_version_id=None, persona_ids=["hook_driven_reader"],
        profile_id="live-test", requested_max_provider_calls=1,
        consent_text_version="live-consent-v1",
    )
    assert error is None and ticket is not None
    result = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert provider.calls == 0
    assert result["status"] == "blocked"
    assert result["safe_error_code"] == "INPUT_TOKEN_BUDGET_EXCEEDED"
    assert result["actual_provider_calls"] == 0


def test_public_profile_counter_metadata_changes_registry_revision(tmp_path: Path):
    class Provider:
        provider_id = "fake-live-provider"
        model_id = "fake-live-model"
        counter_id = "fixture-counter"
        counter_revision = "rev-a"

        def count_request_tokens(self, request):
            return 1

    provider = Provider()
    service = LivePanelExecutionService(_context(tmp_path), provider=provider, profiles={"live-test": _profile()})
    before = service.profile_registry_revision()
    public = service.list_public_profiles()[0]
    assert public["exact_token_counter_available"] is True
    assert public["counter_label"] == "fixture-counter"
    assert public["ready_for_consent"] is True
    assert public["ready_for_live_execution"] is False
    assert public["safe_readiness_code"] == "PROFILE_READY_CAPABILITY_DISABLED"
    provider.counter_revision = "rev-b"
    assert service.profile_registry_revision() != before


def test_counter_revision_is_bound_to_ticket_audit_and_invalidates_old_ticket(tmp_path: Path):
    class Provider:
        provider_id = "fake-live-provider"
        model_id = "fake-live-model"
        counter_id = "fixture-counter"
        counter_revision = "rev-a"
        calls = 0

        def count_request_tokens(self, request):
            return 1

        def generate(self, request):
            self.calls += 1
            raise AssertionError("old ticket reached Provider")

    provider = Provider()
    service = LivePanelExecutionService(_context(tmp_path), provider=provider, profiles={"live-test": _profile()})
    ticket, error = service.issue_consent(
        project_id="hardening-project", timeline_id="main", chapter_id=1,
        source_version_id=None, persona_ids=["hook_driven_reader"], profile_id="live-test",
        requested_max_provider_calls=1, consent_text_version="live-consent-v1",
    )
    assert error is None and ticket is not None
    assert ticket.counter_id == "fixture-counter" and ticket.counter_revision == "rev-a"
    provider.counter_revision = "rev-b"
    result = service.execute_ticket(ticket.ticket_id, ticket.idempotency_key)
    assert result["safe_error_code"] == "PROFILE_REGISTRY_CHANGED"
    assert provider.calls == 0
    audits = [json.loads(path.read_text(encoding="utf-8")) for path in service.store.audits_dir.glob("*.json")]
    assert audits and audits[-1]["counter_id"] == "fixture-counter"
    assert audits[-1]["counter_revision"] == "rev-a"


def test_frontend_shows_only_safe_readiness_and_does_not_add_enablement():
    for marker in (
        "exact_token_counter_available", "counter_label", "counter_revision_short",
        "ready_for_live_execution", "safe_readiness_code",
        "Provider readiness passed", "Production Live remains disabled",
    ):
        assert marker in LIVE_MODULE
    for forbidden in ("credential_configured", "base_url", "api_key", "tokenizer_path"):
        assert forbidden not in LIVE_MODULE
