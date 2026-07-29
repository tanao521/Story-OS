from __future__ import annotations

import json

def test_review_route_is_registered_and_no_store_contract():
    from web.narrative_chapter_routes import router
    route = next(item for item in router.routes if item.path.endswith("/candidates/{candidate_id}/review"))
    assert route.methods == {"POST"}


def test_review_route_errors_are_safe_and_uncached():
    from web.narrative_chapter_routes import _error

    response = _error(RuntimeError("provider secret C:/private/traceback.py"))
    body = response.body.decode("utf-8")
    assert response.headers["cache-control"] == "no-store"
    assert "provider secret" not in body
    assert "C:/private" not in body
    assert "traceback" not in body
    assert json.loads(response.body)["error"]["code"] == "NARRATIVE_OPERATION_FAILED"
