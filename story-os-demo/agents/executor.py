"""Execute one bounded agent and persist a redacted project-local trace."""
from __future__ import annotations

import json
from typing import Any

from agents.builtin import builtin_agents
from agents.memory_scope import scoped_context
from agents.models import now_iso, stable_id
from agents.registry import AgentRegistry
from core.project_context import ProjectContext
from system.data_store import DataStore


def _creative_team_prompt(agent_name: str, visible: dict[str, Any]) -> str:
    """Build a bounded, Chinese-language advisory prompt from scoped context only."""
    context_json = json.dumps(visible, ensure_ascii=False, default=str, indent=2)
    if len(context_json) > 14_000:
        context_json = f"{context_json[:14_000]}\n[上下文已截断]"
    return (
        f"你是小说创作团队中的{agent_name}。请只用简体中文提出具体、可执行的建议。\n"
        "你不能改写正文、提交章节、修改世界观或替作者做决定。\n"
        "请按以下结构作答：\n"
        "1. 核心判断（1—2句）\n"
        "2. 建议方案（3—5条，具体到人物、冲突或场景）\n"
        "3. 风险与作者需要确认的事项\n"
        "避免空泛套话；如果资料不足，请明确指出缺少什么，而不是编造设定。\n\n"
        f"已获授权的项目上下文：\n{context_json}"
    )


class AgentExecutor:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store, self.registry = context, DataStore(context), AgentRegistry(context)

    def execute(self, agent_id: str, context_snapshot: dict[str, Any], *, workflow_run_id: str = "", step_id: str = "") -> dict[str, Any]:
        profile = self.registry.get(agent_id)
        if not profile.enabled:
            raise RuntimeError("AGENT_DISABLED")
        visible = scoped_context(context_snapshot, profile.memory_scope)
        result = builtin_agents({agent_id: profile})[agent_id].run(visible)
        model_reference: dict[str, Any] = {}
        # Model use is opt-in for a workflow run.  Deterministic advice remains
        # the safe default, including all tests.  When enabled, the Stage 8
        # gateway owns routing, limits, retries, and its own model-run record.
        if profile.model_task and bool(context_snapshot.get("allow_model_calls")):
            from llm.model_gateway import get_model_gateway
            prompt = _creative_team_prompt(profile.name, visible)
            result["model_advisory"] = get_model_gateway(self.context).generate_text(
                profile.model_task, prompt, temperature=0.55, max_tokens=1_200, prompt_id=profile.system_prompt_id,
                job_id=workflow_run_id or None,
            )
            model_reference = {"task_type": profile.model_task, "workflow_run_id": workflow_run_id}
        # A trace is diagnostic metadata, not a second manuscript store.
        result = {key: value for key, value in result.items() if key not in {"draft_text", "prompt", "private_notes"}}
        trace = {
            "schema_version": "1.0", "trace_id": stable_id("agent_trace"), "project_id": self.context.root.name,
            "agent_id": profile.id, "workflow_run_id": workflow_run_id, "workflow_step": step_id,
            "model_task": profile.model_task, "system_prompt_id": profile.system_prompt_id,
            "started_at": now_iso(), "finished_at": now_iso(),
            "input_reference": {"context_ref": str(context_snapshot.get("context_ref", "")), "keys": sorted(visible.keys())},
            "output_reference": {"keys": sorted(result.keys()), "contains_full_draft": False, "model_run_reference": model_reference},
            "result": result, "evaluation_scores": result.get("evaluation", {}).get("scores", {}) if isinstance(result.get("evaluation"), dict) else {},
        }
        self.store.write_json(f"data/agents/runs/{trace['trace_id']}.json", trace)
        return trace

    def traces(self, *, workflow_run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        directory = self.store.ensure_directory("data/agents/runs")
        rows: list[dict[str, Any]] = []
        for path in directory.glob("*.json"):
            row = self.store.read_json(path, default={}, expected_type=dict) or {}
            if not workflow_run_id or row.get("workflow_run_id") == workflow_run_id: rows.append(row)
        rows.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        return rows[:max(1, min(limit, 100))]
