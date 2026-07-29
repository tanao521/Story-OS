"""HTTP boundary for the shared Chapter lifecycle authority."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.chapter_lifecycle_adapters import (
    SimulatorChapterLifecycleAdapter,
    TraditionalChapterLifecycleAdapter,
)
from system.chapter_lifecycle_service import ChapterLifecycleError
from web.schemas import ChapterLifecycleCreateRequest


router = APIRouter(prefix="/api/chapter-lifecycle", tags=["chapter-lifecycle"])
_NO_STORE = {"Cache-Control": "no-store"}


def _adapter(source: str):
    context = get_project_context()
    if source == "traditional":
        return TraditionalChapterLifecycleAdapter(context)
    return SimulatorChapterLifecycleAdapter(context)


def _ok(result: dict) -> JSONResponse:
    return JSONResponse(
        {"ok": True, "message": "", "result": result, "warnings": result.get("warnings", []), "errors": []},
        headers=_NO_STORE,
    )


def _fail(exc: ChapterLifecycleError) -> JSONResponse:
    status = 400 if exc.code in {"CHAPTER_LIFECYCLE_ERROR"} else 409
    return JSONResponse(
        {
            "ok": False,
            "message": str(exc),
            "result": {},
            "warnings": [],
            "errors": [exc.code],
        },
        status_code=status,
        headers=_NO_STORE,
    )


@router.get("/next")
def resolve_next_chapter(
    project_id: str,
    timeline_id: str = "main",
    current_chapter_id: int | None = Query(default=None, ge=1),
    source: str = Query(default="traditional", pattern="^(traditional|simulator)$"),
) -> JSONResponse:
    try:
        return _ok(
            _adapter(source).resolve(
                project_id=project_id,
                timeline_id=timeline_id,
                current_chapter_id=current_chapter_id,
            )
        )
    except ChapterLifecycleError as exc:
        return _fail(exc)


@router.post("/next")
def create_next_chapter(payload: ChapterLifecycleCreateRequest) -> JSONResponse:
    try:
        values = payload.model_dump(exclude={"source"})
        return _ok(_adapter(payload.source).create(**values))
    except ChapterLifecycleError as exc:
        return _fail(exc)
