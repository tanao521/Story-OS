from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.project_context import bind_project_context, get_project_context
from core.errors import StoryOSError, public_error
from system.app_logging import get_logger, redact
from system.job_manager import get_job_manager
from web.routes import router
from web.analytics_routes import router as analytics_router
from web.author_routes import router as author_router
from web.creative_loop_routes import router as creative_loop_router

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = get_job_manager()
    manager.startup()
    try:
        yield
    finally:
        manager.shutdown()


app = FastAPI(title="Story OS Web Console", version="2.2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(router)
app.include_router(analytics_router)
app.include_router(author_router)
app.include_router(creative_loop_router)


@app.exception_handler(StoryOSError)
async def storyos_error_handler(request, exc: StoryOSError):
    get_logger("web").warning("%s", redact(exc))
    return JSONResponse({"ok": False, "error": public_error(exc), "message": str(exc), "result": {}, "warnings": [], "errors": [exc.code]}, status_code=409)


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc: Exception):
    get_logger("web").exception("Unhandled web error: %s", redact(exc))
    error = public_error(exc)
    return JSONResponse({"ok": False, "error": error, "message": error["message"], "result": {}, "warnings": [], "errors": [error["code"]]}, status_code=500)


@app.middleware("http")
async def bind_active_project_context(request, call_next):
    """Bind a request to its active project without changing process cwd."""
    with bind_project_context(get_project_context()):
        return await call_next(request)
