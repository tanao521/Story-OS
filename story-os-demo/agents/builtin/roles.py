"""Built-in team roles. They produce bounded advice, never apply it."""
from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from agents.evaluation import CreativeEvaluator


def _chapter_goal(context: dict[str, Any]) -> str:
    plan = context.get("chapter_plan") or context.get("chapter") or {}
    return str(plan.get("goal") or plan.get("summary") or "推动本章发展，并让主角面对清晰且会改变局面的后果。") if isinstance(plan, dict) else "推动本章发展，并让主角面对清晰且会改变局面的后果。"


class RoleAgent(BaseAgent):
    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        role = self.profile.id
        goal = _chapter_goal(context)
        draft = str(context.get("draft_text") or context.get("draft") or "")
        if role == "story_director":
            return {"creative_brief": goal, "decision": "让本章始终兑现当前故事已经建立的核心承诺。",
                    "human_checkpoint": "请确认这份创作简报，再进入后续的情节设计。"}
        if role == "plot_architect":
            return {"goal": goal, "beats": ["向主角施加更具体的压力", "迫使主角做出会付出代价的选择", "以局势发生变化的结果收束本章"],
                    "human_checkpoint": "请确认这份情节方案，再进入写作建议。"}
        if role == "character_psychologist":
            return {"behavior_guardrails": ["人物行动必须先有能理解的动机", "人物关系的变化要符合既有因果"],
                    "simulation": "人物反应应当同时遵循已确立的目标与眼前压力。"}
        if role == "world_builder":
            return {"world_constraints": list((context.get("global_memory") or {}).get("world_rules", []))[:8],
                    "note": "此处仅提供建议，不会修改世界观资料。"}
        if role == "writer":
            return {"draft_direction": goal, "candidate_required": True, "draft_length_seen": len(draft),
                    "note": "写作顾问只给出候选建议，仍需由作者审核。"}
        if role == "editor":
            return {"edit_notes": ["在场景转折处交代清楚因果", "优先用具体行动呈现信息，而不是直接解释"],
                    "candidate_preserved": True}
        if role == "continuity_checker":
            return {"continuity_notes": ["确认前请检查人物状态、时间线与尚未回收的伏笔。"], "blocking": []}
        if role == "reader_simulator":
            evaluation = CreativeEvaluator().evaluate(draft, context)
            return {"reader_profiles": _reader_profiles(draft), "evaluation": evaluation,
                    "note": "读者反馈仅供参考，不会改动正文。"}
        if role == "character_simulator":
            return {"simulation": {"likely_reaction": "人物会在已表明的愿望与眼前风险之间权衡。",
                                    "consistency_question": "这个选择是否仍符合已确立的人物动机？"}}
        if role == "market_analyst":
            return {"market_advice": ["用一句话说清作品承诺给读者的类型体验。", "让主角的第一次关键选择具有足够的辨识度。"], "source": "规则建议", "note": "未使用平台或销售数据。"}
        if role == "audience_analyst":
            return {"audience_advice": ["让读者能迅速理解开场目标。", "用疑问、代价或关系变化来结束场景。"], "source": "读者模拟", "note": "这是读者模拟，不是用户调研。"}
        if role == "story_strategist":
            return {"strategy_options": ["加重当前代价", "揭示一条受限线索", "制造一次关系转折"], "human_checkpoint": "请先选择策略，再调整章节计划。"}
        if role == "retention_analyst":
            return {"retention_risks": ["检查冲突是否在开场场景中及时出现。", "检查结尾是否提出了明确的后续疑问。"], "source": "读者模拟"}
        if role == "author_assistant":
            author = context.get("author_global", {}) if isinstance(context.get("author_global"), dict) else {}
            return {"author_preferences": author.get("preferences", []), "recalled_assets": author.get("retrieved_knowledge", []), "conflicts": (author.get("preference_resolution") or {}).get("conflicts", []), "note": "作者偏好仅在明确选用后才生效；此处不会写入项目资料。"}
        return {"note": "暂无可提供的建议。"}


def _reader_profiles(draft: str) -> list[dict[str, Any]]:
    length = len(draft)
    return [{"persona": name, "focus": focus, "response": "场景转折还可以更鲜明。" if length < 240 else "场景的推进感清晰。"}
            for name, focus in (("动作类型读者", "风险与节奏"), ("剧情类型读者", "情感因果"),
                                ("情感类型读者", "关系张力"), ("文学类型读者", "叙述声音与意象"))]


def builtin_agents(profiles: dict[str, Any]) -> dict[str, BaseAgent]:
    return {agent_id: RoleAgent(profile) for agent_id, profile in profiles.items()}
