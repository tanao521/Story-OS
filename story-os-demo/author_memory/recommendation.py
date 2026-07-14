"""Author copilot: explain relevant habits, never replace a choice."""
from __future__ import annotations

from typing import Any
from author_memory.knowledge_retriever import AuthorKnowledgeRetriever
from core.project_context import ProjectContext

def copilot_advice(context: ProjectContext, query: str, project_rules: list[str]) -> dict[str, Any]:
    memory = AuthorKnowledgeRetriever(context).context_for_task(query, project_rules)
    warnings = [f"可参考作者资产：{item['name']}" for item in memory["retrieved_knowledge"]]
    for row in memory["preference_resolution"]["conflicts"]: warnings.append(f"存在偏好冲突：{row['author_preference']} / {row['project_rule']}")
    return {"advice": warnings or ["尚无匹配作者资产；可以先保存一条偏好、经验或创意。"], "knowledge": memory["retrieved_knowledge"], "conflicts": memory["preference_resolution"]["conflicts"], "source": "author_global", "disclaimer": "建议不自动修改项目规则、章节或作者选择。"}
