"""HTTP boundary for author-owned assets and advisory copilot results."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from author_memory.asset_store import AuthorAssetStore
from author_memory.author_profile import AuthorProfileService
from author_memory.experience_manager import ExperienceManager
from author_memory.recommendation import copilot_advice
from author_memory.style_analyzer import analyze_style
from core.project_context import get_project_context
from system.data_store import DataStore
from web.view_models import api_ok

router = APIRouter(tags=["author"])
def _ctx(): return get_project_context()
async def _body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json(); return value if isinstance(value, dict) else {}
    except Exception: return {}
def _ok(result: dict[str, Any], message: str) -> JSONResponse: return JSONResponse(api_ok(message, result))

@router.get("/api/author/profile")
def profile() -> JSONResponse: return _ok({"profile": AuthorProfileService(_ctx()).profile(), "preferences": AuthorProfileService(_ctx()).preferences()}, "Author profile loaded.")
@router.put("/api/author/profile")
async def update_profile(request: Request) -> JSONResponse: return _ok({"profile": AuthorProfileService(_ctx()).update(await _body(request))}, "Author profile saved.")
@router.put("/api/author/preferences")
async def preferences(request: Request) -> JSONResponse: return _ok({"preferences": AuthorProfileService(_ctx()).update_preferences(await _body(request))}, "Author preferences saved.")
@router.get("/api/author/assets")
def assets(query: str = "") -> JSONResponse: return _ok({"assets": AuthorAssetStore(_ctx()).list_assets(query)}, "Author assets loaded.")
@router.post("/api/author/assets")
async def add_asset(request: Request) -> JSONResponse: return _ok({"asset": AuthorAssetStore(_ctx()).add_asset(await _body(request))}, "Author asset saved.")
@router.get("/api/author/experience")
def experiences() -> JSONResponse: return _ok({"experience": ExperienceManager(_ctx()).list()}, "Author experience loaded.")
@router.post("/api/author/failures")
async def failure(request: Request) -> JSONResponse: return _ok({"failure": ExperienceManager(_ctx()).add_failure(await _body(request))}, "Failure lesson saved.")
@router.post("/api/author/successes")
async def success(request: Request) -> JSONResponse: return _ok({"success": ExperienceManager(_ctx()).add_success(await _body(request))}, "Success pattern saved.")
@router.post("/api/author/style/analyze")
async def style(request: Request) -> JSONResponse:
    body = await _body(request); return _ok(analyze_style(str(body.get("text") or "")), "Style signals analyzed.")
@router.get("/api/author/copilot")
def copilot(query: str = "") -> JSONResponse:
    spec = DataStore(_ctx()).read_json("data/story_spec.json", default={}, expected_type=dict) or {}
    rules = [str(x) for x in spec.get("avoid", [])] + [str(x) for x in (spec.get("writing_constraints") or {}).get("must_follow", [])]
    return _ok(copilot_advice(_ctx(), query, rules), "Author copilot advice prepared.")
