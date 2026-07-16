from __future__ import annotations

from web.api_registry import CANONICAL_ROUTES, COMPATIBILITY_ROUTES, compatibility_headers


def test_compatibility_registry_has_real_routes_and_no_removal_candidates() -> None:
    assert {item.path for item in CANONICAL_ROUTES} >= {
        "/api/planning/overview", "/api/evaluations", "/api/revisions", "/api/versions",
        "/api/narrative-memory/context-preview",
    }
    assert {item.path for item in COMPATIBILITY_ROUTES} >= {
        "/api/quality-report", "/api/continuity-report", "/api/planning/next-chapter",
        "/api/quality-check", "/api/continuity-check",
    }
    assert not any(item.removal_ready for item in COMPATIBILITY_ROUTES)


def test_compatibility_headers_are_additive_and_safe() -> None:
    headers = compatibility_headers("/api/quality-report")
    assert headers == {
        "X-StoryOS-Compatibility": "compatibility",
        "X-StoryOS-Canonical-Endpoint": "/api/evaluations",
    }
    assert compatibility_headers("/api/evaluations") == {}
