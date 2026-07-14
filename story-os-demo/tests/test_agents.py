from __future__ import annotations

from agents.base_agent import AgentPermissionError
from agents.executor import AgentExecutor
from agents.memory_scope import scoped_context
from agents.registry import AgentRegistry
from agents.workflow import WorkflowEngine
from core.project_context import get_project_context
from system.job_manager import JobManager
import time


def _snapshot() -> dict:
    return {"context_ref": "test:chapter:1", "global_memory": {"title": "Test"},
            "characters": {"main_characters": [{"name": "A"}]}, "chapter_plan": {"goal": "Test a choice"},
            "draft_text": "A difficult choice changes the scene.", "secret": "must not leak"}


def test_registry_is_project_scoped_and_can_disable(tmp_path):
    (tmp_path / "left").mkdir(); (tmp_path / "right").mkdir()
    left, right = get_project_context(tmp_path / "left"), get_project_context(tmp_path / "right")
    assert len(AgentRegistry(left).list()) >= 9
    AgentRegistry(left).set_enabled("writer", False)
    assert AgentRegistry(left).get("writer").enabled is False
    AgentRegistry(left).update("writer", {"system_prompt_id": "generic", "model_task": "write_draft"})
    assert AgentRegistry(left).get("writer").system_prompt_id == "generic"
    assert AgentRegistry(right).get("writer").enabled is True


def test_memory_scope_and_permissions_protect_secrets_and_mutation(tmp_path):
    view = scoped_context(_snapshot(), ["draft"])
    assert view["draft_text"] and "secret" not in view and "characters" not in view
    agent = AgentRegistry(get_project_context(tmp_path)).get("writer")
    from agents.builtin.roles import RoleAgent
    try:
        RoleAgent(agent).assert_read_only("write_world")
    except AgentPermissionError:
        pass
    else:
        raise AssertionError("writer must not gain world mutation authority")


def test_workflow_pauses_and_resumes_sequentially_with_traces(tmp_path):
    context = get_project_context(tmp_path)
    engine = WorkflowEngine(context)
    first = engine.start("chapter_creative_v1", _snapshot())
    assert first["status"] == "waiting_for_human" and first["current_step"] == "direct"
    second = engine.resume(first["run_id"], {"direct": True})
    assert second["status"] == "waiting_for_human" and second["current_step"] == "plan"
    final = engine.resume(second["run_id"], {"plan": True})
    assert final["status"] == "completed"
    assert all(step["status"] == "completed" for step in final["steps"])
    traces = AgentExecutor(context).traces(workflow_run_id=final["run_id"])
    assert len(traces) == len(final["steps"])
    assert all("secret" not in str(row.get("input_reference")) for row in traces)
    assert "A difficult choice" not in str(final)


def test_reader_only_receives_draft_and_trace_never_stores_full_draft(tmp_path):
    trace = AgentExecutor(get_project_context(tmp_path)).execute("reader_simulator", _snapshot())
    assert trace["input_reference"]["keys"] == ["context_ref", "draft_text"]
    assert "A difficult choice" not in str(trace)


def test_creative_team_model_call_is_opt_in_and_uses_scoped_context(tmp_path, monkeypatch):
    calls = []

    class Gateway:
        def generate_text(self, task_type, prompt, **kwargs):
            calls.append((task_type, prompt, kwargs))
            return "Model advisory"

    monkeypatch.setattr("llm.model_gateway.get_model_gateway", lambda context: Gateway())
    snapshot = _snapshot() | {"allow_model_calls": True}
    trace = AgentExecutor(get_project_context(tmp_path)).execute("story_director", snapshot)
    assert trace["result"]["model_advisory"] == "Model advisory"
    assert calls[0][0] == "creative_team_advice"
    assert "must not leak" not in calls[0][1]


def test_creative_team_keeps_rule_advice_when_model_route_fails(tmp_path, monkeypatch):
    from llm.model_models import ModelGatewayError

    class Gateway:
        def generate_text(self, *args, **kwargs):
            raise ModelGatewayError("missing route", code="HTTP_404", recoverable=True)

    monkeypatch.setattr("llm.model_gateway.get_model_gateway", lambda context: Gateway())
    trace = AgentExecutor(get_project_context(tmp_path)).execute(
        "reader_simulator", _snapshot() | {"allow_model_calls": True}
    )

    assert trace["result"]["reader_profiles"]
    assert trace["result"]["model_advisory_error"]["code"] == "HTTP_404"
    assert trace["output_reference"]["model_run_reference"]["status"] == "failed"


def test_workflow_uses_persistent_background_job_and_waits_for_author(tmp_path):
    context = get_project_context(tmp_path)
    manager = JobManager(max_workers=1)
    manager.startup()
    try:
        job = manager.create_job("agent_workflow", {"workflow_id": "chapter_creative_v1", "context_snapshot": _snapshot()}, context=context)
        deadline = time.monotonic() + 3
        current = manager.get_job(job["job_id"], context=context)
        while current["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(.02); current = manager.get_job(job["job_id"], context=context)
        assert current["status"] == "waiting_for_review"
        assert current["result"]["workflow_status"] == "waiting_for_human"
    finally:
        manager.shutdown()


def test_workflow_marks_unsatisfied_dependency_failed(tmp_path):
    engine = WorkflowEngine(get_project_context(tmp_path))
    run = engine.start("chapter_creative_v1", _snapshot(), {"direct": True})
    assert run["status"] == "waiting_for_human"
    run["steps"][1]["checkpoint"] = False
    run["steps"][1]["depends_on"] = ["missing-step"]
    result = engine._advance(run)  # Deliberately malformed persisted definition.
    assert result["status"] == "failed"


def test_agent_traces_are_isolated_between_projects(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    first, second = get_project_context(tmp_path / "a"), get_project_context(tmp_path / "b")
    AgentExecutor(first).execute("reader_simulator", _snapshot())
    assert len(AgentExecutor(first).traces()) == 1
    assert AgentExecutor(second).traces() == []


def test_creative_debate_is_advisory_and_never_selects_a_proposal(tmp_path):
    debate = WorkflowEngine(get_project_context(tmp_path)).debate(_snapshot())
    assert debate["status"] == "awaiting_author_choice"
    assert len(debate["proposals"]) == 3
    assert all("director_score" in item and "reader_feedback" in item for item in debate["proposals"])
