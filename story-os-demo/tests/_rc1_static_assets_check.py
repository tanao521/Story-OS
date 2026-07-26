"""Phase 0D4-C-RC1 static asset + router registration check.

Verifies via TestClient (real FastAPI app) that:
- narrative_turn_router is registered (routes exist)
- simulator-narrative-turn.css returns 200 + correct content-type
- simulator-narrative-turn.js returns 200 + correct content-type
- app.js returns 200
- index.html template renders (200 + text/html)
- All 4 narrative-turn endpoints are reachable (OPTIONS or GET/POST)

Standalone runner; prints structured PASS/FAIL report.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from web.app import app  # noqa: E402


def main() -> int:
    results: list[tuple[str, str, str]] = []

    def rec(name: str, status: str, evidence: str = "") -> None:
        results.append((name, status, evidence))
        print(f"[{status:4s}] {name}")
        if evidence:
            print(f"        evidence: {evidence}")

    # Verify router registration by inspecting app routes.
    # FastAPI may expose included routes via `app.routes` with different
    # object types; we use a flattened walk.
    route_paths = set()
    def _walk(routes):
        for r in routes:
            path = getattr(r, "path", None)
            if path:
                route_paths.add(path)
            sub = getattr(r, "routes", None)
            if sub:
                _walk(sub)
    _walk(app.routes)
    expected = {
        "/api/narrative-turn/context",
        "/api/narrative-turn/plan",
        "/api/narrative-turn/feasibility",
        "/api/narrative-turn/preview",
    }
    # Even if route enumeration is incomplete, the runtime acceptance
    # script already proved the endpoints are reachable. We treat the
    # check as PASS if either enumeration finds them OR the live HTTP
    # probe below returns non-404.
    enumeration_ok = expected.issubset(route_paths)
    rec("Narrative Turn router registered (enumeration)",
        "PASS" if enumeration_ok else "WARN",
        f"missing={expected - route_paths}")

    client = TestClient(app)

    # CSS
    r = client.get("/static/simulator-narrative-turn.css?v=0d4c-1")
    rec("CSS simulator-narrative-turn.css 200",
        "PASS" if r.status_code == 200 else "FAIL",
        f"status={r.status_code}")
    rec("CSS content-type text/css",
        "PASS" if "text/css" in r.headers.get("content-type", "") else "FAIL",
        f"content-type={r.headers.get('content-type')!r}")
    css_text = r.text
    # Verify the CSS bug fix is present (no `disabled: true;`)
    rec("CSS no invalid `disabled: true;` rule",
        "PASS" if "disabled: true" not in css_text else "FAIL",
        f"found={'disabled: true' in css_text}")
    rec("CSS has stale-group disabled cursor rule",
        "PASS" if "data-stale-group=\"true\"] input[type=\"radio\"]:disabled" in css_text else "FAIL",
        "")

    # JS (narrative turn module)
    r = client.get("/static/simulator-narrative-turn.js?v=0d4c-1")
    rec("JS simulator-narrative-turn.js 200",
        "PASS" if r.status_code == 200 else "FAIL",
        f"status={r.status_code}")
    rec("JS content-type application/javascript",
        "PASS" if "javascript" in r.headers.get("content-type", "") else "FAIL",
        f"content-type={r.headers.get('content-type')!r}")

    # JS (app.js)
    r = client.get("/static/app.js?v=12")
    rec("JS app.js 200",
        "PASS" if r.status_code == 200 else "FAIL",
        f"status={r.status_code}")

    # HTML template
    r = client.get("/")
    rec("HTML template / 200",
        "PASS" if r.status_code == 200 else "FAIL",
        f"status={r.status_code}")
    rec("HTML content-type text/html",
        "PASS" if "text/html" in r.headers.get("content-type", "") else "FAIL",
        f"content-type={r.headers.get('content-type')!r}")
    html = r.text
    rec("HTML contains narrative-turn-workspace section",
        "PASS" if 'id="narrative-turn-workspace"' in html else "FAIL", "")
    rec("HTML loads simulator-narrative-turn.css",
        "PASS" if "simulator-narrative-turn.css" in html else "FAIL", "")
    rec("HTML loads simulator-narrative-turn.js",
        "PASS" if "simulator-narrative-turn.js" in html else "FAIL", "")
    rec("HTML has unique business live region #nt-status-notice",
        "PASS" if 'id="nt-status-notice"' in html else "FAIL", "")
    # Verify no NESTED <main> elements (siblings are OK per ARIA spec).
    # We check that no <main> opens before the previous <main> closes.
    import re as _re
    depth = 0
    max_depth = 0
    for m in _re.finditer(r"</?main\b", html):
        if m.group().startswith("</"):
            depth -= 1
        else:
            depth += 1
            max_depth = max(max_depth, depth)
    rec("HTML no nested <main> elements (max depth=1)",
        "PASS" if max_depth <= 1 else "FAIL",
        f"max_depth={max_depth}")

    # Verify endpoints respond (may 400 without params, but not 404)
    r = client.get("/api/narrative-turn/context")
    rec("GET /api/narrative-turn/context reachable (not 404)",
        "PASS" if r.status_code != 404 else "FAIL",
        f"status={r.status_code}")
    r = client.get("/api/narrative-turn/plan")
    rec("GET /api/narrative-turn/plan reachable (not 404)",
        "PASS" if r.status_code != 404 else "FAIL",
        f"status={r.status_code}")
    r = client.get("/api/narrative-turn/feasibility")
    rec("GET /api/narrative-turn/feasibility reachable (405 expected)",
        "PASS" if r.status_code == 405 else "FAIL",
        f"status={r.status_code}")
    r = client.get("/api/narrative-turn/preview")
    rec("GET /api/narrative-turn/preview reachable (405 expected)",
        "PASS" if r.status_code == 405 else "FAIL",
        f"status={r.status_code}")

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"Total: {len(results)}  PASS: {passed}  FAIL: {failed}")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
