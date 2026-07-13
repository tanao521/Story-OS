from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.project_context import bind_project_context, get_project_context
from system.job_manager import get_job_manager
from web.routes import router

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


@app.middleware("http")
async def bind_active_project_context(request, call_next):
    """Bind a request to its active project without changing process cwd."""
    with bind_project_context(get_project_context()):
        return await call_next(request)
