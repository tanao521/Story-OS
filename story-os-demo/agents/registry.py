"""Project-persistent configuration for a fixed, auditable built-in team."""
from __future__ import annotations

from typing import Any

from agents.models import AgentProfile
from core.project_context import ProjectContext
from system.data_store import DataStore


def _profiles() -> dict[str, AgentProfile]:
    rows = [
        ("story_director", "故事导演", "明确本章创作简报，不直接生成正文。", "director", ["direct"], "story_director", ["global", "chapter"], "chapter_plan"),
        ("plot_architect", "剧情架构师", "为作者确认而拆解章节节拍。", "planner", ["plan"], "chapter_planner", ["global", "chapter", "character"], "generate_next_chapter_plan"),
        ("character_psychologist", "角色心理顾问", "检查动机与可能反应是否可信。", "character", ["simulate"], "character_simulator", ["character", "chapter"], ""),
        ("world_builder", "世界观顾问", "依据既定规则提出建议，不改写设定。", "world", ["advise"], "world_builder", ["global", "chapter"], ""),
        ("writer", "写作顾问", "提供可审核的正文方向。", "writer", ["write"], "chapter_writer", ["global", "character", "chapter", "draft"], "write_draft"),
        ("editor", "编辑顾问", "提出清晰度与节奏改进建议。", "editor", ["edit"], "chapter_editor", ["global", "character", "chapter", "draft"], "edit_draft"),
        ("continuity_checker", "连续性检查员", "标记事实与因果之间的冲突。", "checker", ["check"], "continuity_checker", ["global", "character", "chapter", "draft"], "continuity_check"),
        ("reader_simulator", "读者模拟器", "给出多类读者的反馈。", "reader", ["review"], "reader_simulator", ["draft"], "quality_review"),
        ("character_simulator", "角色模拟器", "进行受限的角色行为推演。", "simulator", ["simulate"], "character_simulator", ["character", "chapter"], ""),
        ("market_analyst", "市场分析师", "根据本地项目资料梳理类型信号、定位和创作风险。", "analyst", ["analyze"], "market_analyst", ["global", "chapter"], ""),
        ("audience_analyst", "读者分析师", "模拟读者期待，但不宣称使用真实读者数据。", "analyst", ["analyze"], "audience_analyst", ["global", "chapter", "draft"], ""),
        ("story_strategist", "故事策略师", "把分析转化为由作者掌控的连载策略选项。", "strategist", ["advise"], "story_strategist", ["global", "chapter"], ""),
        ("retention_analyst", "留存分析师", "标记开篇与章节结尾可能流失读者的风险。", "analyst", ["analyze"], "retention_analyst", ["chapter", "draft"], ""),
        ("author_assistant", "作者助手", "依据作者自有偏好与素材，提供非强制性的编辑提醒。", "author_copilot", ["advise"], "author_assistant", ["author_global", "global", "chapter"], ""),
    ]
    return {
        row[0]: AgentProfile(
            id=row[0], name=row[1], description=row[2], role=row[3], task_types=row[4],
            system_prompt_id=row[5], memory_scope=row[6], tools=[],
            input_schema={"type": "context_snapshot"}, output_schema={"type": "advisory"},
            evaluation_rules=["需要人工审核"], model_task="creative_team_advice",
        )
        for row in rows
    }


class AgentRegistry:
    path = "data/agents/registry.json"

    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)
        self._builtins = _profiles()

    def _settings(self) -> dict[str, Any]:
        return self.store.read_json(self.path, default={"schema_version": "1.0", "agents": {}}, expected_type=dict) or {"agents": {}}

    def profiles(self) -> dict[str, AgentProfile]:
        settings = self._settings().get("agents", {})
        result: dict[str, AgentProfile] = {}
        for key, base in self._builtins.items():
            item = dict(settings.get(key, {})) if isinstance(settings, dict) else {}
            result[key] = AgentProfile(**{
                **base.public(),
                "enabled": bool(item.get("enabled", base.enabled)),
                "system_prompt_id": str(item.get("system_prompt_id", base.system_prompt_id)),
                "model_task": str(item.get("model_task", base.model_task)),
            })
        return result

    def list(self) -> list[dict[str, Any]]:
        return [profile.public() for profile in self.profiles().values()]

    def get(self, agent_id: str) -> AgentProfile:
        try:
            return self.profiles()[agent_id]
        except KeyError as exc:
            raise KeyError("AGENT_NOT_FOUND") from exc

    def set_enabled(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        return self.update(agent_id, {"enabled": enabled})

    def update(self, agent_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.get(agent_id)
        allowed = {"enabled", "system_prompt_id", "model_task"}
        data = self._settings()
        target = data.setdefault("agents", {}).setdefault(agent_id, {})
        for key, value in changes.items():
            if key in allowed:
                target[key] = bool(value) if key == "enabled" else str(value)
        self.store.write_json(self.path, data, backup=True)
        return self.get(agent_id).public()
