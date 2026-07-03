from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class VersionSelectRequest(BaseModel):
    source_type: Literal["draft", "edited", "manual"]
    version: int


class ManualSaveRequest(BaseModel):
    chapter_id: int
    source_type: Literal["draft", "edited", "manual"]
    source_version: int
    text: str


class ReviewApproveRequest(BaseModel):
    force: bool = False


class TodoCreateRequest(BaseModel):
    title: str
    type: str = "revision"
    priority: str = "medium"
    chapter_id: int | None = None


class AskRequest(BaseModel):
    mode: Literal["state", "memory", "story"] = "story"
    question: str
    use_llm: bool = False
    use_vector: bool = True



class ProjectCreateRequest(BaseModel):
    title: str = ""
    genre: str = ""
    custom_genre: str = ""
    length_type: str = "长篇"
    target_word_count: int = 0
    world_style: str = ""
    tone: str = ""
    writing_style: str = ""
    narration: str = ""
    character_structure: str = ""
    romance_level: str = ""
    focus: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    anti_ai_style_rules: list[str] = Field(default_factory=list)
    need_outline: bool = True
    use_deepseek: bool = False
