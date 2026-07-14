"""Finite, dependency-aware workflows with explicit author checkpoints."""
from __future__ import annotations

from typing import Any

from agents.executor import AgentExecutor
from agents.evaluation import CreativeEvaluator
from agents.models import WorkflowDefinition, WorkflowStep, now_iso, stable_id
from core.project_context import ProjectContext
from system.data_store import DataStore


def builtin_workflows() -> dict[str, WorkflowDefinition]:
    chapter = WorkflowDefinition("chapter_creative_v1", "章节创作会议", "由创作团队给出建议，并在关键步骤等待作者选择。", [
        WorkflowStep("direct", "story_director", "确定创作简报", checkpoint=True),
        WorkflowStep("plan", "plot_architect", "提出情节节拍", ["direct"], checkpoint=True),
        WorkflowStep("character", "character_psychologist", "模拟人物行为", ["plan"]),
        WorkflowStep("write", "writer", "形成写作方向", ["character"]),
        WorkflowStep("edit", "editor", "给出编辑建议", ["write"]),
        WorkflowStep("read", "reader_simulator", "收集读者反馈", ["edit"]),
        WorkflowStep("continuity", "continuity_checker", "检查连续性", ["read"]),
    ])
    commercial = WorkflowDefinition("commercial_review_v1", "Commercial story review", "An advisory market-and-reader review that never selects a story direction automatically.", [
        WorkflowStep("market", "market_analyst", "Map story positioning", checkpoint=True),
        WorkflowStep("audience", "audience_analyst", "Simulate reader expectations", ["market"]),
        WorkflowStep("retention", "retention_analyst", "Flag simulated retention risks", ["audience"]),
        WorkflowStep("strategy", "story_strategist", "Offer serialization options", ["retention"], checkpoint=True),
    ])
    return {chapter.id: chapter, commercial.id: commercial}


class WorkflowEngine:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store, self.executor = context, DataStore(context), AgentExecutor(context)

    def definitions(self) -> list[dict[str, Any]]:
        return [item.public() for item in builtin_workflows().values()]

    def _path(self, run_id: str) -> str: return f"data/agents/workflows/{run_id}.json"
    def get_run(self, run_id: str) -> dict[str, Any]:
        value = self.store.read_json(self._path(run_id), default=None, expected_type=dict)
        if value is None: raise KeyError("WORKFLOW_RUN_NOT_FOUND")
        return value

    def runs(self, workflow_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        directory = self.store.ensure_directory("data/agents/workflows"); rows=[]
        for path in directory.glob("*.json"):
            row=self.store.read_json(path, default={}, expected_type=dict) or {}
            if not workflow_id or row.get("workflow_id") == workflow_id: rows.append(row)
        rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return rows[:max(1, min(limit, 100))]

    def start(self, workflow_id: str, context_snapshot: dict[str, Any], decisions: dict[str, Any] | None = None) -> dict[str, Any]:
        definition = builtin_workflows().get(workflow_id)
        if definition is None: raise KeyError("WORKFLOW_NOT_FOUND")
        # Persist references and bounded structured context only.  Full drafts,
        # prompts and secret notes remain at their source rather than becoming a
        # second hidden copy in workflow history.
        safe_context = {key: value for key, value in context_snapshot.items()
                        if key not in {"draft_text", "draft", "secret", "private_notes", "prompt"}}
        run = {"schema_version":"1.0", "run_id":stable_id("workflow"), "project_id":self.context.root.name,
               "workflow_id":workflow_id, "status":"running", "created_at":now_iso(), "updated_at":now_iso(),
               "context_ref":str(context_snapshot.get("context_ref", "")), "context_snapshot":safe_context,
               "steps":[{"id":item.id,"agent_id":item.agent_id,"label":item.label,"status":"pending","checkpoint":item.checkpoint,"depends_on":item.depends_on,"trace_id":""} for item in definition.steps],
               "human_decisions":dict(decisions or {}), "warnings":[]}
        self.store.write_json(self._path(run["run_id"]), run)
        return self._advance(run)

    def resume(self, run_id: str, decisions: dict[str, Any] | None = None) -> dict[str, Any]:
        run=self.get_run(run_id)
        if run.get("status") in {"completed", "failed", "cancelled"}: return run
        run.setdefault("human_decisions", {}).update(dict(decisions or {})); run["status"]="running"
        return self._advance(run)

    def _advance(self, run: dict[str, Any]) -> dict[str, Any]:
        completed={row["id"] for row in run["steps"] if row.get("status")=="completed"}
        context=dict(run.get("context_snapshot") or {})
        for step in run["steps"]:
            if step.get("status")=="completed": continue
            # A checkpoint is useful only after its proposal is visible.  Older
            # runs may be paused before execution; preserve their behaviour by
            # treating a supplied decision as approval of that old checkpoint.
            if step.get("status") == "waiting_for_human":
                if not run.get("human_decisions", {}).get(step["id"]):
                    run.update({"status":"waiting_for_human","current_step":step["id"]})
                    break
                step.update({"status":"completed","confirmed_at":now_iso(),"confirmation":"author_approved"})
                completed.add(step["id"])
                continue
            if not all(dep in completed for dep in step.get("depends_on", [])):
                step.update({"status":"blocked","message":"前置步骤尚未完成。"}); run["status"]="failed"; break
            try:
                step["status"]="running"; self._save(run)
                trace=self.executor.execute(step["agent_id"], context, workflow_run_id=run["run_id"], step_id=step["id"])
                step.update({"trace_id":trace["trace_id"],"finished_at":now_iso(),"result":trace["result"]})
                context[f"agent_{step['id']}"]=trace["result"]; completed.add(step["id"])
                if step.get("checkpoint"):
                    step.update({"status":"waiting_for_human","message":"请阅读这份方案并明确确认，会议才会继续。"})
                    completed.discard(step["id"])
                    run.update({"status":"waiting_for_human","current_step":step["id"]})
                    break
                step["status"]="completed"
            except Exception as exc:
                step.update({"status":"failed","message":str(exc)[:240]}); run["status"]="failed"; break
        else: run.update({"status":"completed","current_step":""})
        run["context_snapshot"]=context; run["updated_at"]=now_iso(); self._save(run); return run

    def _save(self, run: dict[str, Any]) -> None:
        run["updated_at"]=now_iso(); self.store.write_json(self._path(str(run["run_id"])), run)

    def debate(self, context_snapshot: dict[str, Any]) -> dict[str, Any]:
        """Create bounded alternatives for an author to compare, never select."""
        goal = str((context_snapshot.get("chapter_plan") or {}).get("goal") or "推动当前冲突进一步升级。")
        proposals = [
            {"id": "pressure", "title": "加重压力", "summary": f"通过迫使主角立刻做出有代价的选择，来{goal}"},
            {"id": "reversal", "title": "制造反转", "summary": f"通过揭示表面解法会改变风险等级，来{goal}"},
            {"id": "intimacy", "title": "关系转折", "summary": f"通过一次会留下长远后果的关系抉择，来{goal}"},
        ]
        evaluator = CreativeEvaluator()
        for item in proposals:
            item["director_score"] = evaluator.evaluate(item["summary"], context_snapshot)
            item["reader_feedback"] = [{"persona": "动作类型读者", "score": item["director_score"]["scores"]["hook"]}, {"persona": "剧情类型读者", "score": item["director_score"]["scores"]["emotion"]}]
        record = {"debate_id": stable_id("creative_debate"), "project_id": self.context.root.name, "created_at": now_iso(), "context_ref": str(context_snapshot.get("context_ref", "")), "proposals": proposals, "status": "awaiting_author_choice", "note": "评分只供参考；系统不会自动选用或应用任何方案。"}
        self.store.write_json(f"data/agents/debates/{record['debate_id']}.json", record)
        return record
