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


class VersionArchiveRequest(BaseModel):
    source_type: Literal["draft", "edited", "manual"]
    version: int
    chapter_id: int | None = None


class ManualSaveRequest(BaseModel):
    chapter_id: int
    source_type: Literal["draft", "edited", "manual", "committed"]
    source_version: int
    text: str


class ReviewApproveRequest(BaseModel):
    force: bool = False
    polish: bool | None = None


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

class JobCreateRequest(BaseModel):
    job_type: Literal["run_chapter", "index_vault", "sync_obsidian", "quality_check", "memory_health", "revision_quality_check", "revision_continuity_check", "revision_impact_analysis", "apply_revision", "restore_canon_version", "rebuild_chapter_summary", "reindex_chapter_memory", "sync_revised_chapter_to_obsidian"]
    parameters: dict[str, Any] = Field(default_factory=dict)


class PlanningEntityRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class PlanningReorderRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class RevisionCreateRequest(BaseModel):
    chapter_id: int = Field(ge=1)
    reason: str = ""
    scope: str = ""
    source_version_id: str | None = None


class RevisionCandidateRequest(BaseModel):
    content: str
    source: Literal["manual", "ai_rewrite", "ai_polish", "restored_version", "imported"] = "manual"
    notes: str = ""


class RevisionReviewRequest(BaseModel):
    decision: Literal["approve", "request_changes", "reject"]
    candidate_version_id: str | None = None
    comment: str = ""
    confirmed_risks: bool = False


class CanonRestoreRequest(BaseModel):
    confirmed_risks: bool = False
