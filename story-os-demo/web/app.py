from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routes import router


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Story OS Web Console", version="2.1")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(router)
