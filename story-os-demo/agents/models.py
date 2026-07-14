"""Serializable models for the local creative-team system."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class AgentProfile:
    id: str
    name: str
    description: str
    role: str
    task_types: list[str]
    system_prompt_id: str
    memory_scope: list[str]
    tools: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    evaluation_rules: list[str] = field(default_factory=list)
    model_task: str = ""
    enabled: bool = True

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowStep:
    id: str
    agent_id: str
    label: str
    depends_on: list[str] = field(default_factory=list)
    checkpoint: bool = False

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowDefinition:
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "steps": [step.public() for step in self.steps]}
