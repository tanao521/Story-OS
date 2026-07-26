"""Tests for Phase 0D2B1-RC1: Live Provider Wiring & Execution Semantics.

All tests use FakeModelPersonaProvider or httpx mocking — zero real network calls, zero token consumption.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest

from core.contracts.model_persona_execution import (
    ExecutionMode,
    ExecutionProfile,
    GenerationParameters,
    ModelPersonaExecutionRequest,
    ModelRunStatus,
    StructuredOutputMode,
    compute_provider_config_fingerprint,
)
from core.project_context import ProjectContext, get_project_context
from system.model_persona_execution_service import (
    EXECUTION_PROFILES,
    ModelPersonaExecutionService,
    ProviderRequest,
    ProviderResponse,
)
from system.model_persona_provider_openai import (
    OpenAICompatibleModelPersonaProvider,
    OpenAIProviderAuthError,
    OpenAIProviderError,
    OpenAIProviderRateLimitError,
    normalized_endpoint_identity,
)
from system.model_persona_run_store import ModelPersonaRunStore


# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

def _create_temp_project(tmp_path: Path) -> ProjectContext:
    project_root = tmp_path / "test_project"
    project_root.mkdir(parents=True)

    (project_root / "data").mkdir()
    (project_root / "data" / "chapters").mkdir()
    (project_root / "data" / "drafts").mkdir()
    (project_root / "data" / "manual").mkdir()
    (project_root / "data" / "edited").mkdir()
    (project_root / "data" / "summaries").mkdir()
    (project_root / "data" / "planning").mkdir()
    (project_root / "data" / "versions").mkdir()
    (project_root / "data" / "quality_reports").mkdir()
    (project_root / "data" / "continuity_reports").mkdir()
    (project_root / "data" / "reviews").mkdir()
    (project_root / "data" / "todos").mkdir()
    (project_root / "data" / "context").mkdir()
    (project_root / "data" / "memory").mkdir()
    (project_root / "data" / "pipeline_runs").mkdir()
    (project_root / "data" / "jobs").mkdir()
    (project_root / "data" / "archive").mkdir()
    (project_root / "data" / "narrative_memory").mkdir()
    (project_root / "data" / "narrative_memory" / "events").mkdir()
    (project_root / "data" / "narrative_memory" / "state").mkdir()
    (project_root / "data" / "narrative_memory" / "snapshots").mkdir()
    (project_root / "data" / "model_runs").mkdir()
    (project_root / "data" / "agents").mkdir()
    (project_root / "data" / "agents" / "runs").mkdir()
    (project_root / "data" / "agents" / "workflows").mkdir()
    (project_root / "data" / "creative_loop").mkdir()
    (project_root / "data" / "creative_loop" / "reflections").mkdir()
    (project_root / "data" / "creative_loop" / "health").mkdir()
    (project_root / "data" / "creative_loop" / "issues").mkdir()
    (project_root / "data" / "creative_loop" / "proposals").mkdir()
    (project_root / "data" / "creative_loop" / "experiments").mkdir()
    (project_root / "data" / "creative_loop" / "patterns").mkdir()
    (project_root / "data" / "creative_loop" / "evolution").mkdir()
    (project_root / "data" / "creative_loop" / "outcomes").mkdir()
    (project_root / "data" / "creative_loop" / "events").mkdir()
    (project_root / "data" / "creative_loop" / "audit").mkdir()
    (project_root / "data" / "planning_control").mkdir()
    (project_root / "logs").mkdir()
    (project_root / ".story_os").mkdir()

    (project_root / "data" / "state.json").write_text(
        json.dumps({"current_chapter": 1, "project_id": "test-project", "timeline_id": "main"}),
        encoding="utf-8",
    )
    (project_root / "data" / "story_spec.json").write_text(
        json.dumps({"title": "Test Novel", "genre": "fantasy", "characters": {}}),
        encoding="utf-8",
    )
    (project_root / "data" / "planning" / "planning.json").write_text(
        json.dumps({
            "chapters": [
                {
                    "chapter_number": 1,
                    "chapter_goal": "主角踏上冒险",
                    "pacing_design": {"ending_hook": "神秘的声音"},
                }
            ]
        }),
        encoding="utf-8",
    )
    (project_root / "data" / "chapters" / "chapter_0001.md").write_text(
        "# 第一章\n\n主角站在山顶，风吹过他的脸庞。\n\n他听到了一个神秘的声音。\n\n他决定踏上冒险的旅程。\n",
        encoding="utf-8",
    )
    (project_root / "data" / "drafts" / "draft_v1_ch0001.md").write_text(
        "# 第一章：冒险的开始\n\n主角站在山顶，风吹过他的脸庞。远处的山谷笼罩在薄雾中。\n\n他听到了一个神秘的声音，仿佛来自另一个世界。\n\n\"你终于来了。\" 声音说道。\n\n主角深吸一口气，决定踏上冒险的旅程。\n",
        encoding="utf-8",
    )
    ctx = get_project_context(project_root)
    _create_draft_version(ctx, 1, "第一章内容，主角踏上冒险之旅。")
    return ctx


def _create_draft_version(ctx: ProjectContext, chapter_id: int, content: str, version: int = 1) -> None:
    draft_dir = ctx.root / "data" / "drafts"
    draft_dir.mkdir(exist_ok=True)
    draft_path = draft_dir / f"chapter_{chapter_id:03d}_draft_v{version:03d}.md"
    draft_path.write_text(content, encoding="utf-8")
    json_path = draft_dir / f"chapter_{chapter_id:03d}_draft_v{version:03d}.json"
    json_path.write_text(
        json.dumps({
            "chapter_id": chapter_id,
            "version": version,
            "version_label": f"draft_v{version:03d}",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    versions_index = {
        "version_index": "1.5",
        "chapter_id": chapter_id,
        "timeline_id": "main",
        "versions": [
            {
                "version": version,
                "version_label": f"draft_v{version:03d}",
                "source": "draft",
                "created_at": "2026-01-01T00:00:00Z",
                "status": "completed",
                "summary": f"Draft version {version}",
                "file_path": f"data/drafts/chapter_{chapter_id:03d}_draft_v{version:03d}.md",
                "word_count": len(content),
            }
        ],
    }
    versions_dir = ctx.root / "data" / "versions"
    versions_dir.mkdir(exist_ok=True)
    versions_path = versions_dir / f"chapter_{chapter_id:03d}_versions.json"
    versions_path.write_text(json.dumps(versions_index, ensure_ascii=False), encoding="utf-8")


class FakeModelPersonaProvider:
    provider_id = "fake-provider"
    model_id = "fake-model"

    def __init__(
        self,
        *,
        response_text: Optional[str] = None,
        usage: Optional[dict[str, int]] = None,
        raise_exception: Optional[Exception] = None,
        provider_type: str = "openai_compatible",
    ) -> None:
        self.response_text = response_text
        self.usage = usage
        self.raise_exception = raise_exception
        self.provider_type = provider_type
        self.call_count = 0

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.call_count += 1
        if self.raise_exception:
            raise self.raise_exception
        if self.response_text:
            text = self.response_text
        else:
            text = json.dumps({
                "reader_reaction": "The chapter has strong opening hooks.",
                "strengths": [
                    {"message": "Good start.", "evidence_refs": [], "confidence": "high"}
                ],
                "concerns": [],
                "reader_questions": [],
                "optimization_directions": [],
                "overall_impression": "Solid chapter.",
            })
        return ProviderResponse(
            text=text,
            usage=self.usage,
            provider_request_id=f"req-{self.call_count}",
        )


def _make_live_profile(
    endpoint_identity: str = "endpoint-abc",
    *,
    profile_id: str = "test_live",
    timeout_seconds: float = 5,
) -> ExecutionProfile:
    return ExecutionProfile(
        profile_id=profile_id,
        profile_version="1.0",
        provider_type="openai_compatible",
        provider_id="openai-compatible",
        model_id="test-model",
        generation_parameters=GenerationParameters(
            temperature=0.0,
            max_output_tokens=1024,
            timeout_seconds=timeout_seconds,
        ),
        timeout_seconds=timeout_seconds,
        structured_output_mode=StructuredOutputMode.JSON,
        enabled=True,
        endpoint_identity=endpoint_identity,
    )


def _valid_feedback_json() -> str:
    return json.dumps({
        "reader_reaction": "The opening creates a clear hook.",
        "strengths": [
            {"message": "Strong opening.", "evidence_refs": [], "confidence": "high"}
        ],
        "concerns": [],
        "reader_questions": [],
        "optimization_directions": [],
        "overall_impression": "A focused opening chapter.",
    })


def _provider_envelope(content: str, *, request_id: str = "req-loopback-body") -> bytes:
    return json.dumps({
        "id": request_id,
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 17,
            "completion_tokens": 11,
            "total_tokens": 28,
        },
    }).encode("utf-8")


class _LoopbackState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.request_count = 0
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.body = _provider_envelope(_valid_feedback_json())
        self.headers: dict[str, str] = {"x-request-id": "req-loopback-header"}
        self.delay_seconds = 0.0
        self.redirect_target = "/redirect-target"

    def configure(
        self,
        *,
        status: int = 200,
        body: bytes | None = None,
        headers: Optional[dict[str, str]] = None,
        delay_seconds: float = 0.0,
    ) -> None:
        with self.lock:
            self.request_count = 0
            self.requests = []
            self.status = status
            self.body = body if body is not None else _provider_envelope(_valid_feedback_json())
            self.headers = dict(headers or {})
            self.delay_seconds = delay_seconds


class _LoopbackHandler(BaseHTTPRequestHandler):
    server_version = "StoryOSLoopback/1.0"

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        state: _LoopbackState = self.server.state  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            parsed_body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_body = None

        with state.lock:
            state.request_count += 1
            state.requests.append({
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "json": parsed_body,
            })
            status = state.status
            body = state.body
            headers = dict(state.headers)
            delay_seconds = state.delay_seconds

        if self.path == state.redirect_target:
            status = 200
            body = _provider_envelope(_valid_feedback_json())
            headers = {"x-request-id": "req-unexpected-redirect-follow"}

        if delay_seconds:
            time.sleep(delay_seconds)

        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        return


class _LoopbackStub:
    def __init__(self) -> None:
        self.state = _LoopbackState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
        self.server.daemon_threads = True
        self.server.state = self.state  # type: ignore[attr-defined]
        host, port = self.server.server_address
        assert host == "127.0.0.1"
        self.base_url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


@pytest.fixture
def loopback_stub(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    stub = _LoopbackStub()
    try:
        yield stub
    finally:
        stub.close()


def _execute_through_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub: _LoopbackStub,
    *,
    timeout_seconds: float = 5,
    base_url: Optional[str] = None,
):
    ctx = _create_temp_project(tmp_path)
    profile = _make_live_profile(timeout_seconds=timeout_seconds)
    monkeypatch.setenv("STORYOS_TEST_LIVE_API_KEY", "TEST_SECRET_CANARY_DO_NOT_PERSIST")
    monkeypatch.setenv("STORYOS_TEST_LIVE_BASE_URL", base_url or stub.base_url)
    service = ModelPersonaExecutionService(ctx, profiles={"test_live": profile})
    result = service.execute(ModelPersonaExecutionRequest(
        project_id="test-project",
        timeline_id="main",
        chapter_id=1,
        persona_id="hook_driven_reader",
        execution_mode=ExecutionMode.LIVE,
        execution_profile="test_live",
        allow_model_call=True,
        force=True,
    ))
    return ctx, service, result


# ===========================================================================
# Provider Config Fingerprint Tests
# ===========================================================================

class TestProviderConfigFingerprint:
    def test_same_config_same_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 == fp2

    def test_api_key_not_in_fingerprint(self) -> None:
        fp = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert len(fp) == 64
        assert "sk-" not in fp
        assert "api_key" not in fp.lower()
        assert "authorization" not in fp.lower()

    def test_profile_version_changes_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="2.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 != fp2

    def test_endpoint_identity_changes_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="def456",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 != fp2

    def test_provider_type_changes_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="anthropic",
            profile_id="default",
            profile_version="1.0",
            provider_id="anthropic",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 != fp2

    def test_model_changes_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-3.5-turbo",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 != fp2

    def test_structured_output_mode_changes_fingerprint(self) -> None:
        fp1 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        fp2 = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="none",
            normalized_endpoint_identity="abc123",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert fp1 != fp2

    def test_fingerprint_does_not_expose_endpoint(self) -> None:
        fp = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="default",
            profile_version="1.0",
            provider_id="openai",
            model_id="gpt-4",
            protocol_version="openai-chat-v1",
            structured_output_mode="json",
            normalized_endpoint_identity="abc123def",
            generation_parameters=GenerationParameters(temperature=0.0),
        )
        assert "http" not in fp.lower()
        assert ".com" not in fp.lower()


# ===========================================================================
# Provider Selection Tests
# ===========================================================================

class TestProviderSelection:
    def test_mock_mode_only_uses_mock_provider(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        service = ModelPersonaExecutionService(ctx)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.MOCK,
            execution_profile="mock",
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.COMPLETED
        assert result.provider_id == "mock"
        assert result.execution_mode == ExecutionMode.MOCK

    def test_live_mode_uses_real_provider(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.COMPLETED
        assert result.provider_id == "fake-provider"
        assert result.execution_mode == ExecutionMode.LIVE
        assert provider.call_count == 1

    def test_live_no_provider_config_blocked(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        service = ModelPersonaExecutionService(ctx)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="nonexistent",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.BLOCKED
        assert result.error_code == "INVALID_PROFILE"

    def test_live_no_config_does_not_fallback_mock(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        service = ModelPersonaExecutionService(ctx)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="nonexistent",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.BLOCKED
        assert result.provider_id == ""

    def test_live_provider_failure_does_not_fallback_mock(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=RuntimeError("provider error"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.FAILED
        assert result.provider_id == "fake-provider"
        assert result.provider_id != "mock"

    def test_disabled_profile_blocked(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = ExecutionProfile(
            profile_id="disabled_live",
            profile_version="1.0",
            provider_type="openai_compatible",
            provider_id="openai-compatible",
            model_id="test-model",
            generation_parameters=GenerationParameters(temperature=0.0),
            timeout_seconds=5,
            structured_output_mode=StructuredOutputMode.JSON,
            enabled=False,
            endpoint_identity="abc123",
        )
        profiles = {"disabled_live": profile}
        service = ModelPersonaExecutionService(ctx, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="disabled_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.BLOCKED
        assert result.error_code == "PROVIDER_NOT_CONFIGURED"

    def test_unknown_profile_blocked(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="nonexistent",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.BLOCKED
        assert result.error_code == "INVALID_PROFILE"

    def test_live_without_allow_model_call_blocked(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=False,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.BLOCKED
        assert result.error_code == "MODEL_CALL_BLOCKED"


# ===========================================================================
# Error Semantics Tests
# ===========================================================================

class TestErrorSemantics:
    def test_malformed_json_invalid_output(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(response_text="not json at all")
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.INVALID_OUTPUT
        assert result.error_code == "MODEL_OUTPUT_INVALID"

    def test_unknown_evidence_invalid_output(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        bad_response = json.dumps({
            "reader_reaction": "Bad evidence.",
            "strengths": [
                {"message": "Fake.", "evidence_refs": ["EV-NONEXISTENT-999"], "confidence": "high"}
            ],
            "concerns": [],
            "reader_questions": [],
            "optimization_directions": [],
            "overall_impression": "",
        })
        provider = FakeModelPersonaProvider(response_text=bad_response)
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.INVALID_OUTPUT
        assert result.error_code == "MODEL_EVIDENCE_INVALID"

    def test_forbidden_field_invalid_output(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        bad_response = json.dumps({
            "reader_reaction": "Has forbidden.",
            "engagement_score": 0.95,
            "strengths": [],
            "concerns": [],
            "reader_questions": [],
            "optimization_directions": [],
            "overall_impression": "",
        })
        provider = FakeModelPersonaProvider(response_text=bad_response)
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.INVALID_OUTPUT
        assert result.error_code == "MODEL_OUTPUT_INVALID"

    def test_provider_auth_error(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderAuthError("auth failed"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == "PROVIDER_AUTH_ERROR"

    def test_provider_rate_limit_error(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderRateLimitError("rate limited"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == "PROVIDER_RATE_LIMITED"

    def test_provider_generic_error(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderError("server error"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == "PROVIDER_ERROR"

    def test_error_code_persisted(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderAuthError("auth failed"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        store = ModelPersonaRunStore(ctx)
        loaded = store.load_run(result.execution_id)
        assert loaded is not None
        assert loaded.error_code == "PROVIDER_AUTH_ERROR"


# ===========================================================================
# Single Request Guarantee Tests
# ===========================================================================

class TestSingleRequestGuarantee:
    def test_single_call_on_success(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.COMPLETED
        assert provider.call_count == 1

    def test_single_call_on_malformed_output(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(response_text="not json")
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.INVALID_OUTPUT
        assert provider.call_count == 1

    def test_single_call_on_provider_failure(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderError("fail"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.FAILED
        assert provider.call_count == 1

    def test_no_retry_on_any_failure(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}

        provider = FakeModelPersonaProvider(raise_exception=OpenAIProviderError("500"))
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)
        service.execute(ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        ))
        assert provider.call_count == 1


# ===========================================================================
# Cache Tests with Provider Config
# ===========================================================================

class TestCacheWithProviderConfig:
    def test_same_config_cache_hit(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result1 = service.execute(request)
        assert result1.cache_status == "miss"
        first_count = provider.call_count

        result2 = service.execute(request)
        assert result2.cache_status == "hit"
        assert provider.call_count == first_count

    def test_provider_config_change_causes_cache_miss(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile1 = _make_live_profile(endpoint_identity="v1")
        profiles1 = {"test_live": profile1}
        provider = FakeModelPersonaProvider()
        service1 = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles1)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result1 = service1.execute(request)
        assert result1.cache_status == "miss"
        first_count = provider.call_count

        profile2 = _make_live_profile(endpoint_identity="v2")
        profiles2 = {"test_live": profile2}
        service2 = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles2)
        result2 = service2.execute(request)

        assert result2.cache_status == "miss"
        assert provider.call_count == first_count + 1

    def test_project_isolation_no_cache_sharing(self, tmp_path: Path) -> None:
        proj_a_root = tmp_path / "proj_a"
        proj_b_root = tmp_path / "proj_b"

        for root in [proj_a_root, proj_b_root]:
            root.mkdir(parents=True)
            (root / "data").mkdir()
            (root / "data" / "chapters").mkdir()
            (root / "data" / "drafts").mkdir()
            (root / "data" / "manual").mkdir()
            (root / "data" / "edited").mkdir()
            (root / "data" / "summaries").mkdir()
            (root / "data" / "planning").mkdir()
            (root / "data" / "versions").mkdir()
            (root / "data" / "quality_reports").mkdir()
            (root / "data" / "continuity_reports").mkdir()
            (root / "data" / "reviews").mkdir()
            (root / "data" / "todos").mkdir()
            (root / "data" / "context").mkdir()
            (root / "data" / "memory").mkdir()
            (root / "data" / "pipeline_runs").mkdir()
            (root / "data" / "jobs").mkdir()
            (root / "data" / "archive").mkdir()
            (root / "data" / "narrative_memory").mkdir()
            (root / "data" / "narrative_memory" / "events").mkdir()
            (root / "data" / "narrative_memory" / "state").mkdir()
            (root / "data" / "narrative_memory" / "snapshots").mkdir()
            (root / "data" / "model_runs").mkdir()
            (root / "data" / "agents").mkdir()
            (root / "data" / "agents" / "runs").mkdir()
            (root / "data" / "agents" / "workflows").mkdir()
            (root / "data" / "creative_loop").mkdir()
            (root / "data" / "creative_loop" / "reflections").mkdir()
            (root / "data" / "creative_loop" / "health").mkdir()
            (root / "data" / "creative_loop" / "issues").mkdir()
            (root / "data" / "creative_loop" / "proposals").mkdir()
            (root / "data" / "creative_loop" / "experiments").mkdir()
            (root / "data" / "creative_loop" / "patterns").mkdir()
            (root / "data" / "creative_loop" / "evolution").mkdir()
            (root / "data" / "creative_loop" / "outcomes").mkdir()
            (root / "data" / "creative_loop" / "events").mkdir()
            (root / "data" / "creative_loop" / "audit").mkdir()
            (root / "data" / "planning_control").mkdir()
            (root / "logs").mkdir()
            (root / ".story_os").mkdir()

            (root / "data" / "state.json").write_text(
                json.dumps({"current_chapter": 1, "project_id": "test-project", "timeline_id": "main"}),
                encoding="utf-8",
            )
            (root / "data" / "story_spec.json").write_text(
                json.dumps({"title": "Test Novel", "genre": "fantasy", "characters": {}}),
                encoding="utf-8",
            )
            (root / "data" / "planning" / "planning.json").write_text(
                json.dumps({
                    "chapters": [{
                        "chapter_number": 1,
                        "chapter_goal": "主角踏上冒险",
                        "pacing_design": {"ending_hook": "神秘的声音"},
                    }]
                }),
                encoding="utf-8",
            )
            (root / "data" / "chapters" / "chapter_0001.md").write_text(
                "# 第一章\n\n主角站在山顶，风吹过他的脸庞。\n\n他听到了一个神秘的声音。\n\n他决定踏上冒险的旅程。\n",
                encoding="utf-8",
            )
            (root / "data" / "drafts" / "draft_v1_ch0001.md").write_text(
                "# 第一章：冒险的开始\n\n主角站在山顶，风吹过他的脸庞。远处的山谷笼罩在薄雾中。\n\n他听到了一个神秘的声音，仿佛来自另一个世界。\n\n\"你终于来了。\" 声音说道。\n\n主角深吸一口气，决定踏上冒险的旅程。\n",
                encoding="utf-8",
            )

            draft_dir = root / "data" / "drafts"
            content = "第一章内容，主角踏上冒险之旅。"
            draft_path = draft_dir / "chapter_001_draft_v001.md"
            draft_path.write_text(content, encoding="utf-8")
            json_path = draft_dir / "chapter_001_draft_v001.json"
            json_path.write_text(
                json.dumps({
                    "chapter_id": 1,
                    "version": 1,
                    "version_label": "draft_v001",
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            versions_index = {
                "version_index": "1.5",
                "chapter_id": 1,
                "timeline_id": "main",
                "versions": [
                    {
                        "version": 1,
                        "version_label": "draft_v001",
                        "source": "draft",
                        "created_at": "2026-01-01T00:00:00Z",
                        "status": "completed",
                        "summary": "Draft version 1",
                        "file_path": "data/drafts/chapter_001_draft_v001.md",
                        "word_count": len(content),
                    }
                ],
            }
            versions_dir = root / "data" / "versions"
            versions_path = versions_dir / "chapter_001_versions.json"
            versions_path.write_text(json.dumps(versions_index, ensure_ascii=False), encoding="utf-8")

        ctx_a = get_project_context(proj_a_root)
        ctx_b = get_project_context(proj_b_root)

        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()

        service_a = ModelPersonaExecutionService(ctx_a, provider=provider, profiles=profiles)
        service_b = ModelPersonaExecutionService(ctx_b, provider=provider, profiles=profiles)

        request_common = dict(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )

        result_a1 = service_a.execute(ModelPersonaExecutionRequest(**request_common))
        assert result_a1.cache_status == "miss"
        count_after_a = provider.call_count

        result_b1 = service_b.execute(ModelPersonaExecutionRequest(**request_common))
        assert result_b1.cache_status == "miss"
        assert provider.call_count == count_after_a + 1

        result_a2 = service_a.execute(ModelPersonaExecutionRequest(**request_common))
        assert result_a2.cache_status == "hit"
        assert provider.call_count == count_after_a + 1


# ===========================================================================
# Run Record Tests
# ===========================================================================

class TestRunRecord:
    def test_run_persists_new_fields(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(usage={"prompt_tokens": 100, "completion_tokens": 200})
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        store = ModelPersonaRunStore(ctx)
        loaded = store.load_run(result.execution_id)
        assert loaded is not None
        assert loaded.execution_mode == ExecutionMode.LIVE
        assert loaded.execution_profile == "test_live"
        assert loaded.execution_profile_version == "1.0"
        assert loaded.provider_config_fingerprint
        assert loaded.error_code is None
        assert loaded.provider_request_id is not None
        assert loaded.usage is not None

    def test_api_key_not_in_run_record(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        store = ModelPersonaRunStore(ctx)
        loaded = store.load_run(result.execution_id)
        assert loaded is not None

        run_json = json.dumps(store._run_to_dict(loaded))
        assert "api_key" not in run_json.lower()
        assert "Bearer " not in run_json
        assert "authorization" not in run_json.lower()

    def test_usage_present(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300})
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.usage is not None
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 200
        assert result.usage.total_tokens == 300

    def test_usage_absent(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}
        provider = FakeModelPersonaProvider(usage=None)
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.usage is None


# ===========================================================================
# OpenAI Adapter Tests
# ===========================================================================

class TestOpenAICompatibleAdapter:
    def test_adapter_has_correct_protocol_version(self) -> None:
        assert hasattr(OpenAICompatibleModelPersonaProvider, "protocol_version")
        assert OpenAICompatibleModelPersonaProvider.protocol_version == "chat-completions-v1"

    def test_adapter_initializes_with_config(self) -> None:
        provider = OpenAICompatibleModelPersonaProvider(
            provider_id="test-provider",
            model_id="test-model",
            api_key="test-key",
            base_url="http://localhost:8080",
        )
        assert provider.provider_id == "test-provider"
        assert provider.model_id == "test-model"

    def test_adapter_error_types_defined(self) -> None:
        assert OpenAIProviderAuthError is not None
        assert OpenAIProviderRateLimitError is not None
        assert OpenAIProviderError is not None

    def test_adapter_does_not_expose_api_key(self) -> None:
        provider = OpenAICompatibleModelPersonaProvider(
            provider_id="test-provider",
            model_id="test-model",
            api_key="sk-secret-key-123",
            base_url="http://localhost:8080",
        )
        assert "sk-secret-key-123" not in str(provider)
        assert not hasattr(provider, "api_key")


# ===========================================================================
# Integration Tests with httpx Mocking
# ===========================================================================

class TestOpenAIAdapterHttp:
    def test_http_request_structure(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        profile = _make_live_profile()
        profiles = {"test_live": profile}

        captured_requests: list[dict[str, Any]] = []

        class CapturingProvider(FakeModelPersonaProvider):
            def generate(self, request: ProviderRequest) -> ProviderResponse:
                captured_requests.append({
                    "model_id": request.model_id,
                    "system_prompt": request.system_prompt,
                    "user_prompt": request.user_prompt,
                    "temperature": request.generation_parameters.temperature,
                })
                return super().generate(request)

        provider = CapturingProvider()
        service = ModelPersonaExecutionService(ctx, provider=provider, profiles=profiles)

        request = ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="test_live",
            allow_model_call=True,
        )
        result = service.execute(request)

        assert result.status == ModelRunStatus.COMPLETED
        assert len(captured_requests) == 1
        assert captured_requests[0]["model_id"] == "fake-model"
        assert captured_requests[0]["temperature"] == 0.0
        assert captured_requests[0]["system_prompt"] is not None
        assert captured_requests[0]["user_prompt"] is not None


# ===========================================================================
# Real localhost socket transport verification (RC2-FV)
# ===========================================================================

class TestLocalhostSocketTransport:
    def test_success_wire_contract_count_usage_request_id_and_staleness(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
    ) -> None:
        loopback_stub.state.configure(
            headers={"x-request-id": "req-loopback-header"},
        )
        ctx, service, result = _execute_through_loopback(
            tmp_path, monkeypatch, loopback_stub
        )

        assert result.status == ModelRunStatus.COMPLETED
        assert result.provider_id == "openai-compatible"
        assert result.provider_id != "mock"
        assert result.provider_request_id == "req-loopback-header"
        assert result.usage is not None
        assert result.usage.input_tokens == 17
        assert result.usage.output_tokens == 11
        assert result.usage.total_tokens == 28
        assert loopback_stub.state.request_count == 1

        captured = loopback_stub.state.requests[0]
        assert captured["path"].endswith("/v1/chat/completions")
        assert captured["headers"]["authorization"] == (
            "Bearer TEST_SECRET_CANARY_DO_NOT_PERSIST"
        )
        payload = captured["json"]
        assert set(payload) == {
            "model", "messages", "stream", "temperature", "max_tokens"
        }
        assert payload["model"] == "test-model"
        assert [item["role"] for item in payload["messages"]] == ["system", "user"]
        assert payload["stream"] is False
        wire_json = json.dumps(payload)
        assert "TEST_SECRET_CANARY_DO_NOT_PERSIST" not in wire_json
        assert "api_key" not in wire_json.lower()
        assert str(ctx.root) not in wire_json

        expected_fingerprint = compute_provider_config_fingerprint(
            provider_type="openai_compatible",
            profile_id="test_live",
            profile_version="1.0",
            provider_id="openai-compatible",
            model_id="test-model",
            protocol_version="chat-completions-v1",
            structured_output_mode="json",
            normalized_endpoint_identity=normalized_endpoint_identity(
                loopback_stub.base_url
            ),
            generation_parameters=_make_live_profile().generation_parameters,
            timeout_policy_version="1.0",
        )
        assert result.provider_config_fingerprint == expected_fingerprint
        staleness = service.check_staleness(
            result.execution_id,
            current_provider_config_fingerprint="0" * 64,
        )
        assert staleness.state.value == "stale"
        assert any(reason.value == "provider_config_changed" for reason in staleness.stale_reasons)

    @pytest.mark.parametrize(
        ("body", "expected_status", "expected_error_code"),
        [
            (b"not-json", ModelRunStatus.FAILED, "PROVIDER_ERROR"),
            (
                _provider_envelope("not-json"),
                ModelRunStatus.INVALID_OUTPUT,
                "MODEL_OUTPUT_INVALID",
            ),
            (
                _provider_envelope(json.dumps({
                    "strengths": [],
                    "concerns": [],
                    "reader_questions": [],
                    "optimization_directions": [],
                })),
                ModelRunStatus.INVALID_OUTPUT,
                "MODEL_OUTPUT_INVALID",
            ),
            (
                _provider_envelope(json.dumps({
                    "reader_reaction": "Unsupported evidence.",
                    "strengths": [{
                        "message": "Unsupported.",
                        "evidence_refs": ["EV-UNKNOWN-CANARY"],
                        "confidence": "high",
                    }],
                    "concerns": [],
                    "reader_questions": [],
                    "optimization_directions": [],
                    "overall_impression": "",
                })),
                ModelRunStatus.INVALID_OUTPUT,
                "MODEL_EVIDENCE_INVALID",
            ),
        ],
        ids=("http-malformed", "model-malformed", "schema-missing", "unknown-evidence"),
    )
    def test_invalid_responses_never_retry_or_repair_call(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
        body: bytes,
        expected_status: ModelRunStatus,
        expected_error_code: str,
    ) -> None:
        loopback_stub.state.configure(body=body)
        _, _, result = _execute_through_loopback(
            tmp_path, monkeypatch, loopback_stub
        )

        assert result.status == expected_status
        assert result.error_code == expected_error_code
        assert result.provider_id != "mock"
        assert loopback_stub.state.request_count == 1

    @pytest.mark.parametrize(
        ("status_code", "expected_error_code"),
        [(401, "PROVIDER_AUTH_ERROR"), (429, "PROVIDER_RATE_LIMITED"), (500, "PROVIDER_ERROR")],
    )
    def test_http_errors_have_stable_mapping_and_one_request(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
        status_code: int,
        expected_error_code: str,
    ) -> None:
        loopback_stub.state.configure(
            status=status_code,
            body=b'{"sensitive_error":"TEST_SECRET_CANARY_DO_NOT_PERSIST"}',
        )
        _, _, result = _execute_through_loopback(
            tmp_path, monkeypatch, loopback_stub
        )

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == expected_error_code
        assert result.error in {
            "Provider authentication failed",
            "Provider rate limit exceeded",
            "Provider request failed",
        }
        assert "TEST_SECRET_CANARY_DO_NOT_PERSIST" not in (result.error or "")
        assert loopback_stub.state.request_count == 1

    def test_timeout_has_one_server_request_and_no_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
    ) -> None:
        loopback_stub.state.configure(delay_seconds=0.25)
        _, _, result = _execute_through_loopback(
            tmp_path,
            monkeypatch,
            loopback_stub,
            timeout_seconds=0.05,
        )

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == "PROVIDER_TIMEOUT"
        assert result.error == "Provider request timed out"
        assert result.provider_id == "openai-compatible"
        assert loopback_stub.state.request_count == 1

    def test_redirect_is_not_followed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
    ) -> None:
        loopback_stub.state.configure(
            status=307,
            body=b"",
            headers={"Location": loopback_stub.state.redirect_target},
        )
        _, _, result = _execute_through_loopback(
            tmp_path, monkeypatch, loopback_stub
        )

        assert result.status == ModelRunStatus.FAILED
        assert result.error_code == "PROVIDER_ERROR"
        assert loopback_stub.state.request_count == 1
        assert loopback_stub.state.redirect_target not in [
            item["path"] for item in loopback_stub.state.requests
        ]

    def test_live_default_without_configuration_is_503_semantic(
        self,
        tmp_path: Path,
    ) -> None:
        ctx = _create_temp_project(tmp_path)
        mock_default = ExecutionProfile(
            profile_id="mock",
            provider_type="mock",
            provider_id="mock",
            model_id="mock-persona-v1",
        )
        service = ModelPersonaExecutionService(
            ctx, profiles={"default": mock_default}
        )
        result = service.execute(ModelPersonaExecutionRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_id="hook_driven_reader",
            execution_mode=ExecutionMode.LIVE,
            execution_profile="default",
            allow_model_call=True,
        ))

        assert result.status == ModelRunStatus.BLOCKED
        assert result.error_code == "PROVIDER_NOT_CONFIGURED"

    def test_secret_canaries_absent_from_cli_web_logs_and_run_records(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loopback_stub: _LoopbackStub,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.routes import router

        secret = "TEST_SECRET_CANARY_DO_NOT_PERSIST"
        prompt_canary = "TEST_PROMPT_CANARY_DO_NOT_PERSIST"
        body_canary = "TEST_BODY_CANARY_DO_NOT_PERSIST"
        endpoint_canary = "TEST_ENDPOINT_CANARY_DO_NOT_PERSIST"
        endpoint_url = f"{loopback_stub.base_url}/{endpoint_canary}"
        upstream_error = json.dumps({
            "error": f"{secret}|{prompt_canary}|{body_canary}|{endpoint_canary}"
        }).encode("utf-8")
        loopback_stub.state.configure(status=500, body=upstream_error)

        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, f"{prompt_canary}\n{body_canary}")
        for name, value in {
            "STORYOS_MODEL_PROVIDER": "openai_compatible",
            "STORYOS_MODEL_BASE_URL": endpoint_url,
            "STORYOS_MODEL": "test-model",
            "STORYOS_MODEL_KEY_ENV": "STORYOS_MODEL_API_KEY",
            "STORYOS_MODEL_API_KEY": secret,
            "STORYOS_DEFAULT_BASE_URL": endpoint_url,
            "STORYOS_DEFAULT_API_KEY": secret,
        }.items():
            monkeypatch.setenv(name, value)

        cli = subprocess.run(
            [
                sys.executable,
                "main.py",
                "run-reader-persona-model",
                "--chapter", "1",
                "--persona", "hook_driven_reader",
                "--mode", "live",
                "--execution-profile", "default",
                "--allow-model-call",
                "--force",
                "--project-root", str(ctx.root),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            env=os.environ.copy(),
            timeout=30,
        )
        assert cli.returncode != 0
        assert loopback_stub.state.request_count == 1

        loopback_stub.state.configure(status=500, body=upstream_error)
        live_default = _make_live_profile(
            normalized_endpoint_identity(endpoint_url),
            profile_id="default",
        )
        monkeypatch.setitem(EXECUTION_PROFILES, "default", live_default)
        app = FastAPI()
        app.include_router(router)
        web_response = TestClient(app).post(
            "/api/simulator/reader/personas/model/run",
            json={
                "chapter_id": 1,
                "persona_id": "hook_driven_reader",
                "mode": "live",
                "execution_profile": "default",
                "allow_model_call": True,
                "force": True,
                "project_root": str(ctx.root),
            },
        )
        # 0D3C2-A closes the legacy direct Live route before project/provider
        # resolution; the consent-bound route is the only supported path.
        assert web_response.status_code == 400
        assert "LIVE_REQUIRES_CONSENT_TICKET" in web_response.text
        assert loopback_stub.state.request_count == 0

        runs_dir = ctx.root / "data" / "simulator" / "model_persona_runs"
        serialized_runs = "\n".join(
            path.read_text(encoding="utf-8") for path in runs_dir.glob("*.json")
        )
        captured = capsys.readouterr()
        exposed_surfaces = "\n".join((
            cli.stdout,
            cli.stderr,
            web_response.text,
            caplog.text,
            captured.out,
            captured.err,
            serialized_runs,
        ))
        for canary in (secret, prompt_canary, body_canary, endpoint_canary):
            assert canary not in exposed_surfaces
        assert f"Bearer {secret}" not in exposed_surfaces
        assert "authorization" not in exposed_surfaces.lower()
