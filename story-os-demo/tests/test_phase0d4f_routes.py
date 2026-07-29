from web.app import app


def test_phase0d4f_routes_are_explicit_and_no_store_ready():
    paths = set()
    for route in app.routes:
        router = getattr(route, "original_router", None)
        for child in getattr(router or route, "routes", [route]):
            paths.add(getattr(child, "path", ""))
    assert "/api/narrative-chapter/compile" in paths
    assert "/api/narrative-chapter/commit" in paths
    assert "/api/narrative-chapter/candidates/{candidate_id}" in paths
