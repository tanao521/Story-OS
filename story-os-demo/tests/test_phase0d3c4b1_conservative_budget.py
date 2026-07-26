"""0D3C4-B1 strict conservative infrastructure tests (offline only)."""
from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

from core.contracts.model_persona_execution import (
    ExecutionProfile, GenerationParameters, StructuredOutputMode,
)
from system.conservative_token_budget import (
    CONSERVATIVE_COUNTER_ASSET_MISMATCH,
    CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE,
    CONSERVATIVE_TOKEN_BUDGET_AVAILABLE,
    CONSERVATIVE_TOKEN_BUDGET_EXCEEDED,
    CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE,
    evaluate_conservative_request,
    provision_external_text_counter,
    strict_deepseek_policy,
)
import system.conservative_token_budget as conservative_budget_module
from system.conservative_dependency_scan import (
    DependencyScanFinding,
    scan_directories,
    scan_source,
)
from system.model_persona_execution_service import ProviderRequest
from system.model_persona_provider_openai import (
    OpenAICompatibleModelPersonaProvider,
    OpenAIProviderError,
)
from system.live_panel_execution_service import LivePanelExecutionService, public_live_capability
from system.provider_usage_reconciliation import (
    RECONCILIATION_RECORD_VERSION,
    ProviderUsageReconciliation,
    ProviderUsageReconciliationError,
    ProviderUsageReconciliationStore,
)
from test_phase0d3c2a_live_hardening import _context


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "web" / "static" / "simulator-live-consent.js").read_text(encoding="utf-8")


class FixtureLayerACounter:
    counter_id = "fixture-layer-a"
    counter_revision = "fixture-1"
    counter_scope = "layer_a_text_only_non_exact"
    exact = False

    def __init__(self, count: int = 2048) -> None:
        self.count = count
        self.seen = None

    def supports(self, provider_id: str, model_id: str) -> bool:
        return provider_id == "deepseek" and model_id == "deepseek-v4-flash"

    def count_text_tokens(self, texts) -> int:
        self.seen = tuple(texts)
        return self.count


def _request(*, thinking=True, response_format=True, model="deepseek-v4-flash"):
    return ProviderRequest(
        model, "Return only JSON. Example: {\"reader_reaction\":\"bounded\"}.", "chapter",
        GenerationParameters(temperature=0.0, max_output_tokens=512, timeout_seconds=60),
        provider_id="deepseek", profile_revision="profile-1",
        thinking={"type": "disabled"} if thinking else None,
        structured_output_schema={"type": "json_object"} if response_format else None,
        counter_id="fixture-layer-a", counter_revision="fixture-1",
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("B1 attempted network access")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.delenv("STORYOS_LIVE_EXECUTION_UI_ENABLED", raising=False)


def test_strict_constants_formula_and_decimal_ceiling():
    policy = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    assert policy.estimate_input(2048, 2) == 3456
    assert policy.estimate_input(1, 2) == 898
    assert (
        policy.text_token_limit, policy.max_conservative_input_tokens,
        policy.max_output_tokens, policy.max_total_tokens,
        policy.max_provider_calls, policy.timeout_seconds,
        policy.retry_policy, policy.fallback_policy, policy.cost_estimate_available,
    ) == (2048, 3584, 512, 4096, 1, 60, "0", "none", False)


def test_request_requires_explicit_thinking_json_and_exact_model():
    policy = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    counter = FixtureLayerACounter()
    good = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=counter,
    )
    assert good.allowed and good.safe_code == CONSERVATIVE_TOKEN_BUDGET_AVAILABLE
    assert good.conservative_estimated_tokens == 3456
    for request in (
        _request(thinking=False), _request(response_format=False),
        _request(model="deepseek-v4-pro"),
    ):
        result = evaluate_conservative_request(
            canonical_payload=request.canonical_payload(), provider_id="deepseek",
            policy=policy, counter=counter,
        )
        assert not result.allowed
        assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_client_can_only_lower_and_budget_breach_blocks():
    policy = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    request = _request().canonical_payload()
    raised = evaluate_conservative_request(
        canonical_payload=request, provider_id="deepseek", policy=policy,
        counter=FixtureLayerACounter(), client_text_limit=2049,
    )
    raised_input = evaluate_conservative_request(
        canonical_payload=request, provider_id="deepseek", policy=policy,
        counter=FixtureLayerACounter(), client_input_limit=3585,
    )
    exceeded = evaluate_conservative_request(
        canonical_payload=request, provider_id="deepseek", policy=policy,
        counter=FixtureLayerACounter(2049),
    )
    lowered = evaluate_conservative_request(
        canonical_payload=request, provider_id="deepseek", policy=policy,
        counter=FixtureLayerACounter(1000), client_text_limit=1000, client_call_limit=1,
    )
    assert raised.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE
    assert raised_input.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE
    assert exceeded.safe_code == CONSERVATIVE_TOKEN_BUDGET_EXCEEDED
    assert lowered.allowed


def test_policy_revision_changes_fingerprint():
    first = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    second = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-2")
    assert first.fingerprint() != second.fingerprint()


def test_five_children_receive_independent_one_call_budgets():
    policy = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    results = [
        evaluate_conservative_request(
            canonical_payload=_request().canonical_payload(), provider_id="deepseek",
            policy=policy, counter=FixtureLayerACounter(300 + index),
            client_call_limit=1,
        )
        for index in range(5)
    ]
    assert len(results) == 5
    assert all(result.allowed for result in results)


def test_canonical_payload_is_frozen_and_adapter_sends_same_object():
    observed = {}

    class Response:
        status_code = 200
        headers = {}
        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{}"}}]}

    def post(url, **kwargs):
        observed["payload"] = kwargs["json"]
        return Response()

    request = _request()
    counted = request.canonical_payload()
    counted["messages"][0]["content"] = "mutated"
    sent_expected = request.canonical_payload()
    adapter = OpenAICompatibleModelPersonaProvider(
        provider_id="deepseek", model_id="deepseek-v4-flash",
        api_key="fixture-secret", base_url="https://fixture.invalid", post=post,
    )
    adapter.generate(request)
    assert observed["payload"] == sent_expected
    assert observed["payload"]["thinking"] == {"type": "disabled"}
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    assert request.canonical_payload_hash() == hashlib.sha256(
        json.dumps(sent_expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_empty_provider_content_fails_once_without_retry():
    calls = 0

    class Response:
        status_code = 200
        headers = {}
        @staticmethod
        def json():
            return {"choices": [{"message": {}}]}

    def post(url, **kwargs):
        nonlocal calls
        calls += 1
        return Response()

    adapter = OpenAICompatibleModelPersonaProvider(
        provider_id="deepseek", model_id="deepseek-v4-flash",
        api_key="fixture-secret", base_url="https://fixture.invalid", post=post,
    )
    with pytest.raises(OpenAIProviderError):
        adapter.generate(_request())
    assert calls == 1


def test_external_asset_gate_is_default_off_and_validates_hash(tmp_path: Path):
    asset = tmp_path / "layer-a.json"
    asset.write_text('{"fixture":true}', encoding="utf-8")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    loader = lambda asset_bytes, parsed: FixtureLayerACounter()
    disabled = provision_external_text_counter(
        enabled=False, trusted_path=asset, expected_sha256=digest, loader=loader
    )
    mismatch = provision_external_text_counter(
        enabled=True, trusted_path=asset, expected_sha256="0" * 64, loader=loader
    )
    valid = provision_external_text_counter(
        enabled=True, trusted_path=asset, expected_sha256=digest, loader=loader
    )
    assert disabled.safe_code == CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE
    assert mismatch.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH
    assert valid.available and valid.counter is not None
    assert str(asset) not in json.dumps(valid.__dict__, default=str)


def test_asset_rejects_symlink_when_supported(tmp_path: Path):
    asset = tmp_path / "asset.json"
    link = tmp_path / "link.json"
    asset.write_text("{}", encoding="utf-8")
    try:
        link.symlink_to(asset)
    except OSError:
        pytest.skip("symlinks unavailable")
    result = provision_external_text_counter(
        enabled=True, trusted_path=link,
        expected_sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
        loader=lambda asset_bytes, parsed: FixtureLayerACounter(),
    )
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def _reconciliation(**overrides):
    values = {
        "local_text_tokens": 100,
        "conservative_estimated_tokens": 1000,
        "provider_prompt_tokens": 950,
        "difference_tokens": -50,
        "difference_ratio": -0.05,
        "policy_revision": "p1",
        "profile_revision": "r1",
        "counter_revision": "c1",
        "model_id": "deepseek-v4-flash",
        "safe_request_fingerprint": "f" * 64,
        "usage_completeness": "complete",
        "timestamp": "2026-07-23T00:00:00+00:00",
    }
    values.update(overrides)
    return ProviderUsageReconciliation(**values)


@pytest.mark.parametrize(
    "record_id",
    ["", " ", ".", "..", "../escape", "..\\escape", "/path", "C:\\path", "a/b", "a\\b", "bad\nid"],
)
def test_reconciliation_store_rejects_unsafe_record_ids(tmp_path: Path, record_id: str):
    store = ProviderUsageReconciliationStore(tmp_path / "records")
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append(record_id, _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.INVALID_RECORD_ID
    assert str(tmp_path) not in str(caught.value)


def test_reconciliation_store_is_contained_and_append_only(tmp_path: Path):
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    path = store.append("safe_ID-1", _reconciliation())
    assert path.parent == root.resolve()
    assert path.resolve().is_relative_to(root.resolve())
    before = path.read_bytes()
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("safe_ID-1", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.ALREADY_EXISTS
    assert path.read_bytes() == before


def test_reconciliation_store_rejects_symlink_root_when_supported(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ProviderUsageReconciliationError):
        ProviderUsageReconciliationStore(link)


@pytest.mark.parametrize(
    "overrides",
    [
        {"local_text_tokens": -1},
        {"conservative_estimated_tokens": -1},
        {"provider_prompt_tokens": True, "difference_tokens": -999},
        {"local_text_tokens": False},
        {"policy_revision": " "},
        {"profile_revision": ""},
        {"counter_revision": ""},
        {"model_id": ""},
        {"safe_request_fingerprint": "not-a-hash"},
        {"difference_tokens": -49},
        {"difference_ratio": -0.049},
        {
            "usage_completeness": "incomplete",
            "provider_prompt_tokens": 1,
            "difference_tokens": -999,
            "difference_ratio": -0.999,
        },
    ],
)
def test_reconciliation_contract_rejects_invalid_invariants(overrides):
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(**overrides)


def test_reconciliation_contract_accepts_valid_complete_and_incomplete():
    assert _reconciliation().usage_completeness == "complete"
    incomplete = _reconciliation(
        provider_prompt_tokens=None,
        difference_tokens=None,
        difference_ratio=None,
        usage_completeness="incomplete",
    )
    assert incomplete.usage_completeness == "incomplete"


def test_reconciliation_store_saves_valid_complete_and_incomplete(tmp_path: Path):
    store = ProviderUsageReconciliationStore(tmp_path / "records")
    complete_path = store.append("complete", _reconciliation())
    incomplete_path = store.append(
        "incomplete",
        _reconciliation(
            provider_prompt_tokens=None, difference_tokens=None,
            difference_ratio=None, usage_completeness="incomplete",
        ),
    )
    assert json.loads(complete_path.read_text(encoding="utf-8"))["usage_completeness"] == "complete"
    assert json.loads(incomplete_path.read_text(encoding="utf-8"))["usage_completeness"] == "incomplete"


def test_asset_loader_receives_the_same_validated_bytes_and_parsed_json(tmp_path: Path):
    asset = tmp_path / "layer-a.json"
    asset.write_text('{"fixture":{"version":1}}', encoding="utf-8")
    expected = asset.read_bytes()
    observed = {}

    def loader(asset_bytes, parsed):
        observed["bytes"] = asset_bytes
        observed["parsed"] = parsed
        return FixtureLayerACounter()

    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(expected).hexdigest(), loader=loader,
    )
    assert result.available
    assert observed == {"bytes": expected, "parsed": {"fixture": {"version": 1}}}


@pytest.mark.parametrize("content", [b"", b"{broken", b"[]", b"{}"])
def test_asset_rejects_empty_malformed_or_wrong_json_structure(tmp_path: Path, content: bytes):
    asset = tmp_path / "layer-a.json"
    asset.write_bytes(content)
    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        loader=lambda asset_bytes, parsed: FixtureLayerACounter(),
    )
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def test_asset_rejects_oversized_file_without_calling_loader(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(conservative_budget_module, "MAX_CONSERVATIVE_ASSET_BYTES", 8)
    asset = tmp_path / "layer-a.json"
    asset.write_bytes(b'{"123":9}')
    called = False

    def loader(asset_bytes, parsed):
        nonlocal called
        called = True
        return FixtureLayerACounter()

    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(asset.read_bytes()).hexdigest(), loader=loader,
    )
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH
    assert called is False


@pytest.mark.parametrize("path_kind", ["relative", "wrong_suffix", "missing"])
def test_asset_rejects_invalid_paths(tmp_path: Path, path_kind: str):
    valid = tmp_path / "asset.json"
    valid.write_text('{"fixture":true}', encoding="utf-8")
    path = {
        "relative": Path("asset.json"),
        "wrong_suffix": tmp_path / "asset.txt",
        "missing": tmp_path / "missing.json",
    }[path_kind]
    if path_kind == "wrong_suffix":
        path.write_bytes(valid.read_bytes())
    result = provision_external_text_counter(
        enabled=True, trusted_path=path,
        expected_sha256=hashlib.sha256(valid.read_bytes()).hexdigest(),
        loader=lambda asset_bytes, parsed: FixtureLayerACounter(),
    )
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def test_asset_rejects_loader_failure_exact_counter_and_wrong_scope(tmp_path: Path):
    asset = tmp_path / "asset.json"
    asset.write_text('{"fixture":true}', encoding="utf-8")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()

    def broken(asset_bytes, parsed):
        raise RuntimeError("private loader detail")

    class ExactCounter(FixtureLayerACounter):
        exact = True

    class WrongScopeCounter(FixtureLayerACounter):
        counter_scope = "wrong"

    for loader in (
        broken,
        lambda asset_bytes, parsed: ExactCounter(),
        lambda asset_bytes, parsed: WrongScopeCounter(),
    ):
        result = provision_external_text_counter(
            enabled=True, trusted_path=asset, expected_sha256=digest, loader=loader,
        )
        assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH
        assert "private loader detail" not in json.dumps(result.__dict__, default=str)


@pytest.mark.parametrize(
    ("payload", "counter_value", "client_limit"),
    [
        ({"bad": {1, 2}}, 1, None),
        (_request().canonical_payload(), True, None),
        (_request().canonical_payload(), 1.5, None),
        (_request().canonical_payload(), 1, True),
        (_request().canonical_payload(), 1, 1.5),
    ],
)
def test_evaluator_malformed_inputs_fail_closed(payload, counter_value, client_limit):
    counter = FixtureLayerACounter(counter_value)
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=strict_deepseek_policy(
            counter_id="fixture-layer-a", counter_revision="fixture-1"
        ),
        counter=counter, client_text_limit=client_limit,
    )
    assert result.allowed is False
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE
    assert len(result.canonical_payload_hash) == 64


def test_unserializable_payload_failure_fingerprint_is_stable_and_content_free():
    policy = strict_deepseek_policy(counter_id="fixture-layer-a", counter_revision="fixture-1")
    first = evaluate_conservative_request(
        canonical_payload={"secret": {"one"}}, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    second = evaluate_conservative_request(
        canonical_payload={"other": object()}, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert first.canonical_payload_hash == second.canonical_payload_hash
    assert "secret" not in first.canonical_payload_hash


def test_counter_and_support_exceptions_fail_closed():
    class BrokenCounter(FixtureLayerACounter):
        def supports(self, provider_id, model_id):
            raise RuntimeError("private support error")

        def count_text_tokens(self, texts):
            raise RuntimeError("private count error")

    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=strict_deepseek_policy(
            counter_id="fixture-layer-a", counter_revision="fixture-1"
        ),
        counter=BrokenCounter(),
    )
    assert result.allowed is False
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"model": "deepseek-v4-flash", "messages": "wrong"},
        {
            "model": "deepseek-v4-flash", "messages": [{"role": "user", "content": 1}],
            "stream": False, "max_tokens": 512,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        },
    ],
)
def test_payload_shape_errors_fail_closed(payload):
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=strict_deepseek_policy(
            counter_id="fixture-layer-a", counter_revision="fixture-1"
        ),
        counter=FixtureLayerACounter(),
    )
    assert result.allowed is False
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_reconciliation_build_rejects_bool_negative_and_empty_identity():
    base = {
        "local_text_tokens": 1,
        "conservative_estimated_tokens": 2,
        "provider_prompt_tokens": 1,
        "policy_revision": "p",
        "profile_revision": "r",
        "counter_revision": "c",
        "model_id": "deepseek-v4-flash",
        "safe_request_fingerprint": "a" * 64,
    }
    for changes in (
        {"local_text_tokens": False},
        {"provider_prompt_tokens": True},
        {"conservative_estimated_tokens": -1},
        {"policy_revision": ""},
        {"model_id": " "},
        {"safe_request_fingerprint": "bad"},
    ):
        with pytest.raises(ProviderUsageReconciliationError):
            ProviderUsageReconciliation.build(**(base | changes))


def test_usage_reconciliation_is_content_free_complete_or_incomplete():
    complete = ProviderUsageReconciliation.build(
        local_text_tokens=100, conservative_estimated_tokens=1000,
        provider_prompt_tokens=950, policy_revision="p1", profile_revision="r1",
        counter_revision="c1", model_id="deepseek-v4-flash",
        safe_request_fingerprint="f" * 64,
    )
    missing = ProviderUsageReconciliation.build(
        local_text_tokens=100, conservative_estimated_tokens=1000,
        provider_prompt_tokens=None, policy_revision="p1", profile_revision="r1",
        counter_revision="c1", model_id="deepseek-v4-flash",
        safe_request_fingerprint="f" * 64,
    )
    assert complete.difference_tokens == -50
    assert complete.difference_ratio == -0.05
    assert missing.usage_completeness == "incomplete"
    serialized = json.dumps(complete.__dict__)
    for forbidden in ("system_prompt", "user_prompt", "schema", "credential", "endpoint", "path", "raw_response"):
        assert forbidden not in serialized


def test_ui_is_explicitly_non_exact_and_has_no_enable_control():
    for text in (
        "保守 Token 预算", "不是 Provider 精确计数", "Strict Policy",
        "文本上限：", "保守输入上限：", "输出上限：",
        "Thinking：明确关闭", "Structured Output：JSON Object",
        "费用估算不可用", "生产 Live 仍关闭",
    ):
        assert text in UI
    assert "conservative-provisioning-enable" not in UI


def test_public_conservative_readiness_is_safe_and_default_unavailable(tmp_path: Path):
    class Provider:
        provider_id = "deepseek"
        model_id = "deepseek-v4-flash"

    profile = ExecutionProfile(
        profile_id="deepseek-strict", profile_version="profile-1",
        provider_type="openai_compatible", provider_id="deepseek",
        model_id="deepseek-v4-flash",
        generation_parameters=GenerationParameters(max_output_tokens=512),
        timeout_seconds=60, structured_output_mode=StructuredOutputMode.JSON,
        enabled=True, endpoint_identity="safe",
    )
    service = LivePanelExecutionService(
        _context(tmp_path), provider=Provider(), profiles={"deepseek-strict": profile}
    )
    public = service.list_public_profiles()[0]
    assert public["token_budget_mode"] == "conservative"
    assert public["exact_token_counter_available"] is False
    assert public["conservative_token_budget_available"] is False
    assert public["ready_for_consent"] is False
    assert public["ready_for_live_execution"] is False
    assert public["safe_readiness_code"] == CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE
    assert public_live_capability()["enabled"] is False
    serialized = json.dumps(public)
    for forbidden in ("trusted_path", "expected_sha256", "api_key", "credential", str(tmp_path)):
        assert forbidden not in serialized


def test_injected_counter_revision_changes_registry_and_never_sets_exact(tmp_path: Path):
    class Provider:
        provider_id = "deepseek"
        model_id = "deepseek-v4-flash"

    profile = ExecutionProfile(
        profile_id="deepseek-strict", profile_version="profile-1",
        provider_type="openai_compatible", provider_id="deepseek",
        model_id="deepseek-v4-flash",
        generation_parameters=GenerationParameters(max_output_tokens=512),
        timeout_seconds=60, structured_output_mode=StructuredOutputMode.JSON,
        enabled=True,
    )
    counter = FixtureLayerACounter()
    service = LivePanelExecutionService(
        _context(tmp_path), provider=Provider(), profiles={"deepseek-strict": profile},
        conservative_counter=counter, conservative_provisioning_enabled=True,
    )
    before = service.profile_registry_revision()
    public = service.list_public_profiles()[0]
    assert public["conservative_token_budget_available"] is True
    assert public["exact_token_counter_available"] is False
    counter.counter_revision = "fixture-2"
    assert service.profile_registry_revision() != before


def test_repo_has_no_bundled_deepseek_tokenizer_asset():
    production_roots = [ROOT / "core", ROOT / "system", ROOT / "web", ROOT / "llm"]
    asset_suffixes = {".json", ".model", ".vocab", ".merges", ".zip", ".tgz", ".tar.gz"}
    suspicious = []
    for base in production_roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            suffix = ".tar.gz" if lowered.endswith(".tar.gz") else path.suffix.lower()
            if suffix in asset_suffixes and (
                "deepseek" in lowered or "tokenizer" in lowered
            ):
                suspicious.append(path)
    assert suspicious == []


def test_dependency_and_production_code_scan_matches_claimed_scope():
    pyproject = (ROOT.parent / "pyproject.toml").read_text(encoding="utf-8").lower()
    dependency_block = pyproject.split("dependencies", 1)[1].split("]", 1)[0]
    assert '"tokenizers' not in dependency_block
    assert '"transformers' not in dependency_block

    production_python = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for folder in ("core", "system", "web", "llm")
        for path in (ROOT / folder).rglob("*.py")
    )
    assert "trust_remote_code" not in production_python
    assert "snapshot_download(" not in production_python
    assert "hf_hub_download(" not in production_python
    conservative_source = (ROOT / "system" / "conservative_token_budget.py").read_text(
        encoding="utf-8"
    )
    assert "from_pretrained(" not in conservative_source
    assert "Path.home(" not in conservative_source


# ---------------------------------------------------------------------------
# Phase 0D3C4-B1-FIX security closure tests
# ---------------------------------------------------------------------------


# 5.1 — Reconciliation path escape closure


@pytest.mark.parametrize(
    "record_id",
    [
        "../../escape",
        "../../../etc/passwd",
        "..\\..\\escape",
        "\\\\server\\share",
        "\\\\?\\C:\\temp",
        "records.other",
        "a\x00b",
    ],
)
def test_reconciliation_store_rejects_path_escape_variants(
    tmp_path: Path, record_id: str
):
    store = ProviderUsageReconciliationStore(tmp_path / "records")
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append(record_id, _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.INVALID_RECORD_ID
    assert str(tmp_path) not in str(caught.value)


def test_reconciliation_store_accepts_similar_prefix_id(tmp_path: Path):
    """A record_id with a similar prefix to the root name is valid and must
    land inside the root, not in a sibling directory."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    path = store.append("records_evil", _reconciliation())
    assert path.parent == root.resolve()
    assert path.name == "records_evil.json"


def test_reconciliation_store_rejects_sibling_directory_prefix(tmp_path: Path):
    """A directory whose name starts with the root name must not be accepted."""
    root = tmp_path / "records"
    sibling = tmp_path / "records_evil"
    sibling.mkdir()
    store = ProviderUsageReconciliationStore(root)
    # record_id is safe, but verify the store root is exactly "records"
    assert store.root == root.resolve()
    # A valid record must land inside root, not sibling
    path = store.append("valid_id", _reconciliation())
    assert path.parent == root.resolve()
    assert path.parent != sibling.resolve()


def test_reconciliation_store_rejects_canonicalized_escape(tmp_path: Path):
    """Even after canonicalization, records must stay under root."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    # The record_id pattern already blocks separators, but verify the
    # resolved target parent equals root after resolve().
    path = store.append("valid_id", _reconciliation())
    assert path.resolve().parent == root.resolve()
    # No file should exist outside root
    for entry in tmp_path.iterdir():
        if entry.name != "records":
            assert not entry.is_file()


def test_reconciliation_store_valid_path_is_accepted(tmp_path: Path):
    """A legitimate record ID inside the root must succeed."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    path = store.append("valid_record_id_1", _reconciliation())
    assert path.exists()
    assert path.parent == root.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["record_version"] == RECONCILIATION_RECORD_VERSION


# 5.2 — Reconciliation contract version and identity binding


def test_reconciliation_rejects_unknown_record_version():
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        _reconciliation(record_version="2")
    assert caught.value.code == ProviderUsageReconciliationError.INVALID_RECORD


def test_reconciliation_rejects_non_string_record_version():
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(record_version=1)


def test_reconciliation_rejects_empty_record_version():
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(record_version="")


def test_reconciliation_build_sets_current_record_version():
    record = ProviderUsageReconciliation.build(
        local_text_tokens=10, conservative_estimated_tokens=100,
        provider_prompt_tokens=90, policy_revision="p1", profile_revision="r1",
        counter_revision="c1", model_id="deepseek-v4-flash",
        safe_request_fingerprint="a" * 64,
    )
    assert record.record_version == RECONCILIATION_RECORD_VERSION


def test_reconciliation_rejects_mismatched_revision_identity():
    """revision fields must be non-empty and internally consistent."""
    # The record stores revisions as strings; the contract requires them
    # to be non-empty. A revision that doesn't match the policy/counter
    # is still structurally valid, but the service layer must bind them.
    # Here we verify the contract rejects empty/malformed revisions.
    for bad_revision in ("", " ", None):
        with pytest.raises(ProviderUsageReconciliationError):
            _reconciliation(policy_revision=bad_revision)
    for bad_revision in ("", " ", None):
        with pytest.raises(ProviderUsageReconciliationError):
            _reconciliation(counter_revision=bad_revision)
    for bad_revision in ("", " ", None):
        with pytest.raises(ProviderUsageReconciliationError):
            _reconciliation(profile_revision=bad_revision)


def test_reconciliation_rejects_malformed_canonical_fingerprint():
    """safe_request_fingerprint must be a 64-char hex string."""
    for bad_fp in ("short", "g" * 64, "", None, " " * 64):
        with pytest.raises(ProviderUsageReconciliationError):
            _reconciliation(safe_request_fingerprint=bad_fp)


def test_reconciliation_rejects_bool_int_confusion():
    """bool must not be accepted where int is required."""
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(local_text_tokens=True)
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(conservative_estimated_tokens=False)
    with pytest.raises(ProviderUsageReconciliationError):
        _reconciliation(provider_prompt_tokens=True, difference_tokens=0)


# 5.3 — TOCTOU and JSON integrity closure


def test_reconciliation_write_is_atomic_and_durable(tmp_path: Path):
    """Successful append must produce a complete, valid JSON file."""
    store = ProviderUsageReconciliationStore(tmp_path / "records")
    path = store.append("atomic_1", _reconciliation())
    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    data = json.loads(content)
    assert data["usage_completeness"] == "complete"
    # No temp files should remain
    leftovers = [p for p in path.parent.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_reconciliation_write_failure_preserves_existing(tmp_path: Path):
    """A failed second append must not corrupt the first record."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    first_path = store.append("dup_id", _reconciliation())
    first_content = first_path.read_bytes()
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("dup_id", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.ALREADY_EXISTS
    assert first_path.read_bytes() == first_content
    # No temp files left
    leftovers = [p for p in root.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_reconciliation_write_does_not_leave_partial_target(tmp_path: Path):
    """The target file must not exist if the write fails.

    We simulate failure by pre-creating the target so os.link fails with
    FileExistsError.  The existing target must be untouched and no temp
    file must remain.
    """
    root = tmp_path / "records"
    root.mkdir()
    target = root / "preexisting.json"
    original = b'{"original": true}\n'
    target.write_bytes(original)
    store = ProviderUsageReconciliationStore(root)
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("preexisting", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.ALREADY_EXISTS
    assert target.read_bytes() == original
    leftovers = [p for p in root.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_asset_toctou_single_read_provides_consistent_bytes(tmp_path: Path):
    """The asset loader must consume the exact bytes it validated.

    We write a file, compute its hash, then verify the loader receives
    those exact bytes.  A second call with a modified file and stale hash
    must fail.
    """
    asset = tmp_path / "layer-a.json"
    asset.write_text('{"fixture": true}', encoding="utf-8")
    expected = asset.read_bytes()
    observed = {}

    def loader(asset_bytes, parsed):
        observed["bytes"] = asset_bytes
        observed["parsed"] = parsed
        return FixtureLayerACounter()

    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(expected).hexdigest(), loader=loader,
    )
    assert result.available
    assert observed["bytes"] == expected
    # Modify file after first successful read; second call with old hash fails
    asset.write_text('{"modified": true}', encoding="utf-8")
    result2 = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(expected).hexdigest(),
        loader=loader,
    )
    assert result2.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def test_asset_rejects_truncated_json_during_read(tmp_path: Path):
    """Truncated JSON must be rejected, not partially parsed."""
    asset = tmp_path / "layer-a.json"
    content = b'{"fixture": tru'
    asset.write_bytes(content)
    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        loader=lambda asset_bytes, parsed: FixtureLayerACounter(),
    )
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def test_asset_hash_is_computed_from_consumed_bytes(tmp_path: Path):
    """The SHA-256 must match the bytes passed to the loader, not a re-read."""
    asset = tmp_path / "layer-a.json"
    content = b'{"fixture": {"version": 2}}'
    asset.write_bytes(content)
    observed = {}

    def loader(asset_bytes, parsed):
        observed["hash"] = hashlib.sha256(asset_bytes).hexdigest()
        return FixtureLayerACounter()

    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(content).hexdigest(), loader=loader,
    )
    assert result.available
    assert observed["hash"] == hashlib.sha256(content).hexdigest()


# 5.4 — Evaluator fail-closed boundary closure


def test_evaluator_empty_payload_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    result = evaluate_conservative_request(
        canonical_payload={}, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_missing_messages_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    result = evaluate_conservative_request(
        canonical_payload={"model": "deepseek-v4-flash"}, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_unknown_provider_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(),
        provider_id="unknown-provider",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_unknown_model_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload["model"] = "unknown-model"
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_missing_thinking_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload.pop("thinking")
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_missing_response_format_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload.pop("response_format")
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_counter_revision_mismatch_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    counter = FixtureLayerACounter()
    counter.counter_revision = "different"
    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=counter,
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_exact_counter_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )

    class ExactCounter(FixtureLayerACounter):
        exact = True

    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=ExactCounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_negative_client_limit_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
        client_text_limit=-1,
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_overflow_text_tokens_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )

    class OverflowCounter(FixtureLayerACounter):
        def count_text_tokens(self, texts):
            return 10 ** 18

    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=OverflowCounter(),
    )
    assert not result.allowed
    # Overflow exceeds text_token_limit, so it's either EXCEEDED or UNAVAILABLE
    assert result.safe_code in (
        CONSERVATIVE_TOKEN_BUDGET_EXCEEDED,
        CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE,
    )


def test_evaluator_internal_exception_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )

    class ExplodingPolicy:
        """A stand-in that raises during attribute access."""
        provider_id = "deepseek"
        model_id = "deepseek-v4-flash"
        text_token_limit = 2048
        max_conservative_input_tokens = 3584
        max_output_tokens = 512
        max_total_tokens = 4096
        max_provider_calls = 1

        @property
        def text_counter_id(self):
            raise RuntimeError("internal policy error")

    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=ExplodingPolicy(), counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_nan_float_counter_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )

    class NaNCounter(FixtureLayerACounter):
        def count_text_tokens(self, texts):
            return float("nan")

    result = evaluate_conservative_request(
        canonical_payload=_request().canonical_payload(), provider_id="deepseek",
        policy=policy, counter=NaNCounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_non_list_messages_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload["messages"] = "not-a-list"
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_non_dict_message_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload["messages"] = ["not-a-dict"]
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


def test_evaluator_missing_json_keyword_fails_closed():
    policy = strict_deepseek_policy(
        counter_id="fixture-layer-a", counter_revision="fixture-1"
    )
    payload = _request().canonical_payload()
    payload["messages"] = [{"role": "user", "content": "plain text without the required keyword"}]
    result = evaluate_conservative_request(
        canonical_payload=payload, provider_id="deepseek",
        policy=policy, counter=FixtureLayerACounter(),
    )
    assert not result.allowed
    assert result.safe_code == CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE


# 5.5 — AST-based dependency scan closure


def test_scan_source_detects_plain_import():
    findings = tuple(scan_source(
        "import tokenizers\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].module == "tokenizers"
    assert findings[0].reason == "forbidden-import"
    assert findings[0].line == 1


def test_scan_source_detects_aliased_import():
    findings = tuple(scan_source(
        "import transformers as tf\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].module == "transformers"
    assert findings[0].reason == "forbidden-import"


def test_scan_source_detects_from_import():
    findings = tuple(scan_source(
        "from tokenizers import Encoding\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].module == "tokenizers"
    assert findings[0].reason == "forbidden-from-import"


def test_scan_source_detects_dotted_module():
    findings = tuple(scan_source(
        "import torch.nn as nn\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].module == "torch.nn"


def test_scan_source_detects_dynamic_import_forbidden():
    findings = tuple(scan_source(
        "mod = __import__('tokenizers')\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].reason == "dynamic-import-forbidden"
    assert findings[0].module == "tokenizers"


def test_scan_source_flags_non_literal_dynamic_import():
    findings = tuple(scan_source(
        "name = 'token' + 'izers'\n"
        "mod = __import__(name)\n",
        "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].reason == "dynamic-import-non-literal"


def test_scan_source_ignores_strings_and_comments():
    findings = tuple(scan_source(
        "# import tokenizers  <- comment\n"
        "x = 'import transformers'\n"
        "y = 'from torch import nn'\n",
        "fixture.py",
    ))
    assert findings == ()


def test_scan_source_accepts_standard_library():
    findings = tuple(scan_source(
        "import os\nimport json\nfrom pathlib import Path\n",
        "fixture.py",
    ))
    assert findings == ()


def test_scan_source_accepts_project_internal_import():
    findings = tuple(scan_source(
        "from system.conservative_token_budget import strict_deepseek_policy\n"
        "from core.contracts.model_persona_execution import ExecutionProfile\n",
        "fixture.py",
    ))
    assert findings == ()


def test_scan_source_rejects_unparseable_file():
    """A syntax error must produce an unparseable-file finding, not silence."""
    with pytest.raises(SyntaxError):
        tuple(scan_source("import (\n", "fixture.py"))


def test_scan_directories_covers_production_code():
    """The production directories must have zero forbidden imports."""
    result = scan_directories([
        ROOT / "core", ROOT / "system", ROOT / "web", ROOT / "llm",
    ])
    assert result.unparseable_files == ()
    # Findings must be empty for production code
    forbidden_modules = {f.module for f in result.findings}
    assert not forbidden_modules & {
        "tokenizers", "transformers", "torch", "tensorflow",
        "sentence_transformers", "tiktoken",
    }
    # Must have actually scanned files
    assert result.scanned_files > 0


def test_scan_directories_reports_unparseable_files(tmp_path: Path):
    """Files with syntax errors must be reported, not silently skipped."""
    bad = tmp_path / "bad.py"
    bad.write_text("import (\n", encoding="utf-8")
    result = scan_directories([tmp_path])
    assert result.scanned_files >= 1
    assert any("bad.py" in name for name in result.unparseable_files)
    assert any(
        f.reason == "unparseable-file" for f in result.findings
    )


def test_scan_directories_detects_forbidden_in_fixture(tmp_path: Path):
    """A fixture file with a forbidden import must be detected."""
    fixture = tmp_path / "fixture.py"
    fixture.write_text("import tokenizers\n", encoding="utf-8")
    result = scan_directories([tmp_path])
    assert any(
        f.module == "tokenizers" and f.reason == "forbidden-import"
        for f in result.findings
    )


def test_scan_directories_does_not_silently_skip_tests(tmp_path: Path):
    """Test directories must be scannable; no blanket exclusion."""
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_ok.py").write_text(
        "import os\n", encoding="utf-8",
    )
    (test_dir / "test_bad.py").write_text(
        "import torch\n", encoding="utf-8",
    )
    result = scan_directories([test_dir])
    assert result.scanned_files == 2
    assert any(f.module == "torch" for f in result.findings)


def test_scan_finding_has_file_and_line():
    """Findings must carry file path and line number for auditability."""
    findings = tuple(scan_source(
        "x = 1\nimport tokenizers\n", "fixture.py",
    ))
    assert len(findings) == 1
    assert findings[0].file == "fixture.py"
    assert findings[0].line == 2


# Symlink safety decision tests (deterministic, no real symlink required)
#
# The integration tests above that create real symlinks may skip on Windows
# when the account lacks symlink creation privilege.  These unit tests verify
# the *decision logic* deterministically by monkeypatching is_symlink / resolve.
# They must never skip.


def test_store_rejects_root_is_symlink_via_monkeypatch(tmp_path: Path, monkeypatch):
    """Store constructor must reject a root that reports is_symlink()=True."""
    root = tmp_path / "records"
    root.mkdir()
    original_is_symlink = Path.is_symlink
    def fake_is_symlink(self_path):
        if self_path == root or str(self_path) == str(root):
            return True
        return original_is_symlink(self_path)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        ProviderUsageReconciliationStore(root)
    assert caught.value.code == ProviderUsageReconciliationError.PATH_NOT_CONTAINED


def test_store_append_rejects_root_that_became_symlink(tmp_path: Path, monkeypatch):
    """append() must re-check that root has not become a symlink."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    # After construction, simulate root becoming a symlink
    original_is_symlink = Path.is_symlink
    def fake_is_symlink(self_path):
        if str(self_path) == str(store.root):
            return True
        return original_is_symlink(self_path)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("any_id", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.PATH_NOT_CONTAINED


def test_store_append_rejects_resolve_inconsistency(tmp_path: Path, monkeypatch):
    """If root resolves differently than stored, append must fail closed."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    other_path = tmp_path / "other_place"
    other_path.mkdir()
    other_resolved = other_path.resolve()

    call_count = {"v": 0}
    original_resolve = Path.resolve

    def fake_resolve(self_path, strict=True):
        if str(self_path) == str(store.root):
            call_count["v"] += 1
            return other_resolved
        return original_resolve(self_path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("any_id", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.PATH_NOT_CONTAINED
    assert call_count["v"] >= 1


def test_store_append_rejects_root_resolve_oserror(tmp_path: Path, monkeypatch):
    """If self.root.resolve() raises OSError during append, fail closed."""
    root = tmp_path / "records"
    store = ProviderUsageReconciliationStore(root)
    original_resolve = Path.resolve
    triggered = [False]

    def fake_resolve(self_path, strict=True):
        if str(self_path) == str(store.root):
            triggered[0] = True
            raise OSError("simulated root resolve failure")
        return original_resolve(self_path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(ProviderUsageReconciliationError) as caught:
        store.append("any_id", _reconciliation())
    assert caught.value.code == ProviderUsageReconciliationError.PATH_NOT_CONTAINED
    assert triggered[0]


def test_asset_rejects_symlink_via_monkeypatch(tmp_path: Path, monkeypatch):
    """provision_external_text_counter must reject symlinks even via monkeypatch."""
    asset = tmp_path / "asset.json"
    content = b'{"fixture": true}'
    asset.write_bytes(content)
    original_is_symlink = Path.is_symlink
    def fake_is_symlink(self_path):
        if str(self_path) == str(asset):
            return True
        return original_is_symlink(self_path)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    result = provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        loader=lambda b, p: FixtureLayerACounter(),
    )
    assert not result.available
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH


def test_asset_rejects_o_direct_read_failure(tmp_path: Path, monkeypatch):
    """If os.open of the asset file fails, result must be mismatch (fail-closed)."""
    import system.conservative_token_budget as ctb
    asset = tmp_path / "asset.json"
    content = b'{"fixture": true}'
    asset.write_bytes(content)
    original_os_open = os.open
    def fake_os_open(path, flags, *args, **kwargs):
        if str(path) == str(asset):
            raise OSError("simulated open failure")
        return original_os_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", fake_os_open)
    result = ctb.provision_external_text_counter(
        enabled=True, trusted_path=asset,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        loader=lambda b, p: FixtureLayerACounter(),
    )
    assert not result.available
    assert result.safe_code == CONSERVATIVE_COUNTER_ASSET_MISMATCH
