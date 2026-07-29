"""Isolated Chromium fixture for Phase 0D4-D-RC1.

The first confirm request is fully executed and its successful response is
intentionally replaced with a transient 503. A real browser can then retry the
same UI action and prove that the frontend reuses its logical operation ID.
No production route or real project data is changed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from _rc2_browser_fixture_server import setup_workspace


def main() -> None:
    import uvicorn

    workspace = Path(tempfile.mkdtemp(prefix="rc1_browser_ws_"))
    info = setup_workspace(workspace)
    os.chdir(workspace)

    from web.app import app

    state: dict[str, object] = {
        "dropped": False,
        "operation_id": None,
        "confirm_requests": 0,
    }

    @app.middleware("http")
    async def simulate_first_confirm_response_loss(request: Request, call_next):
        if request.url.path != "/api/narrative-turn/confirm":
            return await call_next(request)
        state["confirm_requests"] = int(state["confirm_requests"]) + 1
        body = await request.body()
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        response = await call_next(request)
        if not state["dropped"] and response.status_code == 200:
            state["dropped"] = True
            state["operation_id"] = payload.get("operation_id")
            return JSONResponse(
                status_code=503,
                content={"detail": "RC1 simulated response loss after durable completion"},
                headers={"Cache-Control": "no-store"},
            )
        return response

    @app.get("/__rc1/status")
    async def rc1_status():
        return JSONResponse(
            content={
                **state,
                "workspace": str(workspace),
                "project_id": info["project_id"],
            },
            headers={"Cache-Control": "no-store"},
        )

    print(
        json.dumps(
            {
                "workspace": str(workspace),
                "url": (
                    "http://127.0.0.1:7863/?mode=simulator&view=narrative-turn"
                    f"&project_id={info['project_id']}&timeline_id={info['timeline_id']}"
                    f"&branch_id={info['active_branch']}&chapter_id={info['chapter_id']}"
                ),
            }
        ),
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=7863, reload=False, log_level="info")


if __name__ == "__main__":
    main()
