"""Isolated HTTP/browser-contract acceptance for Phase 0D5-C.

The harness intentionally uses the temporary fixture and TestClient: it
exercises the same route/DOM/network contract without opening a real project,
Provider, Canon, or Chroma.  A full Chromium run remains an RC gate.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._rc2_browser_fixture_server import setup_workspace


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="phase0d5c_browser_"))
    info = setup_workspace(tmp)
    old = os.getcwd(); os.chdir(tmp)
    try:
        from web.app import app
        with TestClient(app) as client:
            checks = []
            page = client.get("/")
            checks.append("simulator-usable-loop.js" in page.text and "data-simulator-loop-shell" in page.text)
            branches = client.get("/api/narrative-branches", params={"project_id": info["project_id"], "timeline_id": info["timeline_id"]})
            checks.append(branches.status_code == 200 and branches.headers.get("cache-control") == "no-store")
            state = client.get("/api/simulator/state", params={"project_id": info["project_id"], "timeline_id": info["timeline_id"], "chapter_id": info["chapter_id"], "branch_id": info["active_branch"]})
            checks.append(state.status_code == 200 and state.json().get("result", {}).get("scope", {}).get("branch_id") == info["active_branch"])
            traditional = client.get("/api/versions", params={"chapter": info["chapter_id"]})
            checks.append(traditional.status_code in {200, 404})
        total = len(checks); passed = sum(checks)
        print(f"Total: {total} PASS: {passed} FAIL: {total - passed} SKIP: 0")
        return 0 if passed == total else 1
    finally:
        os.chdir(old)


if __name__ == "__main__":
    raise SystemExit(main())
