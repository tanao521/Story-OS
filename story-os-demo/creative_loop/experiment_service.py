"""Isolated creative experiments; variants never become canon automatically."""
from __future__ import annotations

from typing import Any

from agents.evaluation import CreativeEvaluator
from core.project_context import ProjectContext
from creative_loop.models import EXPERIMENT_STATUSES, new_id, now_iso
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore


class ExperimentService:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def list(self) -> list[dict[str, Any]]:
        root = self.store.ensure_directory(self.context.creative_experiments_dir); rows=[]
        for path in root.glob("*.json"):
            row = self.store.read_json(path, default=None, expected_type=dict)
            if row: rows.append(row)
        return sorted(rows, key=lambda item: item.get("created_at", ""), reverse=True)

    def get(self, experiment_id: str) -> dict[str, Any]:
        row = self.store.read_json(f"data/creative_loop/experiments/{experiment_id}.json", default=None, expected_type=dict)
        if not row: raise KeyError("EXPERIMENT_NOT_FOUND")
        return row

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        experiment = {"schema_version": "13.1", "experiment_id": new_id("experiment"), "project_id": self.context.root.name, "experiment_type": str(data.get("experiment_type") or "next_chapter_opening"), "goal": str(data.get("goal") or "比较不同创作方向的局部效果。"), "constraints": [str(item) for item in data.get("constraints", []) if str(item)] if isinstance(data.get("constraints"), list) else [], "source_chapter_id": data.get("source_chapter_id"), "source_canon_version_id": str(data.get("source_canon_version_id") or ""), "variants": [], "status": "draft", "status_history": [], "selected_variant_id": None, "created_at": now_iso(), "updated_at": now_iso(), "disclaimer": "实验内容是隔离候选，不会自动写入正史、计划、记忆或作者知识资产。"}
        self.store.write_json(f"data/creative_loop/experiments/{experiment['experiment_id']}.json", experiment, backup=True)
        LifecycleService(self.context).audit("experiment_created", entity_type="experiment", entity_id=experiment["experiment_id"], operator="user")
        return experiment

    def generate_variants(self, experiment_id: str, count: int = 2) -> dict[str, Any]:
        experiment = self.get(experiment_id)
        if experiment.get("status") != "draft": raise RuntimeError("EXPERIMENT_NOT_EDITABLE")
        LifecycleService(self.context).transition(experiment, "experiment", "generating", operator="system", reason="生成隔离实验方案")
        total = max(2, min(int(count), 3)); variants=[]
        for ordinal in range(total):
            focus = ("直接冲突", "关系转折", "线索揭示")[ordinal]
            variants.append({"variant_id": new_id("variant"), "label": chr(65 + ordinal), "focus": focus, "content": f"围绕“{experiment['goal']}”的{focus}方案：保持既定约束，安排一个可观察的选择与代价。", "status": "candidate", "evaluations": []})
        experiment.update({"variants": variants}); LifecycleService(self.context).transition(experiment, "experiment", "evaluating", operator="system", reason="候选方案已生成，等待评估"); self._save(experiment); return experiment

    def evaluate(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get(experiment_id)
        if experiment.get("status") != "evaluating": raise RuntimeError("EXPERIMENT_NOT_EVALUATABLE")
        evaluator = CreativeEvaluator()
        for variant in experiment.get("variants", []):
            scores = evaluator.evaluate(str(variant.get("content") or ""), {})
            variant["evaluations"] = [{"agent": "creative_critic", "source": "rule_based", "scores": scores}, {"agent": "reader_simulator", "source": "ai_simulation", "summary": "模拟读者反馈，仅供创作判断。"}]
        LifecycleService(self.context).transition(experiment, "experiment", "waiting_author", operator="system", reason="实验评估完成，等待作者选择"); self._save(experiment); return experiment

    def select(self, experiment_id: str, variant_id: str) -> dict[str, Any]:
        experiment = self.get(experiment_id)
        if experiment.get("status") != "waiting_author": raise RuntimeError("EXPERIMENT_NOT_SELECTABLE")
        if not any(row.get("variant_id") == variant_id for row in experiment.get("variants", [])): raise KeyError("EXPERIMENT_VARIANT_NOT_FOUND")
        experiment.update({"selected_variant_id": variant_id}); LifecycleService(self.context).transition(experiment, "experiment", "selected", operator="user", reason="作者选择候选方案"); self._save(experiment); LifecycleService(self.context).audit("experiment_selected", entity_type="experiment", entity_id=experiment_id, operator="user", details={"variant_id": variant_id}); return experiment

    def cancel(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get(experiment_id); LifecycleService(self.context).transition(experiment, "experiment", "cancelled", operator="user", reason="作者取消实验"); self._save(experiment); return experiment

    def _save(self, experiment: dict[str, Any]) -> None: self.store.write_json(f"data/creative_loop/experiments/{experiment['experiment_id']}.json", experiment, backup=True)
