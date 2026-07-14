from __future__ import annotations

from pathlib import Path

import pytest

from core.project_context import get_project_context
from llm.model_gateway import ModelGateway
from llm.model_models import ModelGatewayError, ModelRequest, ModelResponse
from llm.model_registry import ModelRegistry
from llm.run_recorder import RunRecorder
from system.data_store import DataStore
from system.job_manager import JobManager


class FakeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def generate(self, definition, request):
        self.calls.append(definition.model_key)
        if self.fail and definition.model_key == "primary":
            raise ModelGatewayError("temporary timeout", code="NETWORK_ERROR", recoverable=True)
        return ModelResponse("测试结果", definition.provider, definition.model, {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})

    def health_check(self, definition):
        return {"status": "configured"}


def make_registry(tmp_path: Path, *, local_only: bool = False) -> tuple[ModelRegistry, object]:
    workspace = tmp_path / "workspace"; project = workspace / "projects" / "alpha"
    project.mkdir(parents=True)
    context = get_project_context(project)
    root_context = get_project_context(workspace)
    DataStore(root_context).write_json(".story_os/models.json", {"models": [
        {"model_key": "primary", "provider": "fake", "model": "p", "api_key_env": "", "base_url": "fake"},
        {"model_key": "fallback", "provider": "fake", "model": "f", "api_key_env": "", "base_url": "fake", "local": True},
    ], "routes": {"planning_analysis": {"primary": "primary", "fallbacks": ["fallback"], "local_only": local_only}}})
    return ModelRegistry(context, workspace_root=workspace), context


def test_gateway_records_usage_and_fallback(tmp_path: Path) -> None:
    registry, context = make_registry(tmp_path)
    provider = FakeProvider(fail=True)
    gateway = ModelGateway(context, registry=registry, recorder=RunRecorder(context), providers={"fake": provider})
    result = gateway.generate(ModelRequest(task_type="planning_analysis", prompt="short prompt", prompt_id="generic"))
    assert result.text == "测试结果"
    assert provider.calls == ["primary", "primary", "fallback"]
    runs = gateway.recorder.list()
    assert runs[0]["status"] == "completed_with_fallback"
    assert runs[0]["usage"]["total_tokens"] == 8
    assert "short prompt" not in str(runs[0])


def test_local_only_never_uses_cloud_fallback(tmp_path: Path) -> None:
    registry, context = make_registry(tmp_path, local_only=True)
    provider = FakeProvider()
    gateway = ModelGateway(context, registry=registry, recorder=RunRecorder(context), providers={"fake": provider})
    assert gateway.generate(ModelRequest(task_type="planning_analysis", prompt="x")).text == "测试结果"
    assert provider.calls == ["fallback"]


def test_routes_are_project_scoped_and_frozen(tmp_path: Path) -> None:
    registry, _ = make_registry(tmp_path)
    frozen = registry.frozen_route("planning_analysis")
    registry.update_routes({"planning_analysis": {"primary": "fallback", "fallbacks": [], "local_only": True}})
    assert frozen["model_key"] == "primary"
    assert registry.route("planning_analysis").primary == "fallback"


def test_creative_team_has_a_dedicated_qwen_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "alpha"
    project.mkdir(parents=True)
    registry = ModelRegistry(get_project_context(project), workspace_root=workspace)
    assert registry.route("creative_team_advice").primary == "qwen"
    assert registry.model("qwen").provider == "openai_compatible"


def test_project_token_limit_blocks_before_provider_call(tmp_path: Path) -> None:
    registry, context = make_registry(tmp_path)
    registry.update_limits({"max_total_tokens": 1})
    provider = FakeProvider()
    gateway = ModelGateway(context, registry=registry, recorder=RunRecorder(context), providers={"fake": provider})
    with pytest.raises(ModelGatewayError, match="token limit"):
        gateway.generate(ModelRequest(task_type="planning_analysis", prompt="long enough to exceed the limit"))
    assert provider.calls == []


def test_run_recorder_sanitizes_secret_like_errors(tmp_path: Path) -> None:
    _, context = make_registry(tmp_path)
    recorder = RunRecorder(context)
    run = recorder.start(task_type="planning_analysis", model_key="primary", provider="fake", model="p", prompt_id="generic", prompt_version="1", prompt_hash="hash", job_id=None, chapter_id=None, route_snapshot={})
    recorder.finish(run, status="failed", usage={}, cost={}, error="Bearer sk-super-secret")
    assert "super-secret" not in recorder.get(run["run_id"])["error"]


def test_model_route_is_frozen_in_project_job_record(tmp_path: Path) -> None:
    registry, context = make_registry(tmp_path)
    # Point the default workspace resolver at an explicitly prepared registry root.
    manager = JobManager(max_workers=1, runner=lambda job, context, emit, cancelled: {"ok": True})
    manager.startup()
    try:
        job = manager.create_job("quality_check", context=context)
        stored = DataStore(context).read_json(context.jobs_dir / f"{job['job_id']}.json", default={}, expected_type=dict)
        route = stored["parameters"]["model_routing"]
        assert route["task_type"] == "quality_review"
        assert route["resolved_model"]
        assert route["routing_policy_version"]
    finally:
        manager.shutdown()
