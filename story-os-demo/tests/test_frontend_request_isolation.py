from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_primary_frontend_request_layer_cancels_stale_project_requests_and_polling() -> None:
    script = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
    assert "AbortController" in script
    assert "storyosRequestGeneration" in script
    assert 'window.addEventListener("storyos:project-changed", clearProjectScopedUi)' in script
    assert 'window.dispatchEvent(new CustomEvent("storyos:project-changed",{detail:{projectId:id}}))' in script
    assert 'window.addEventListener("pagehide", () => { cancelProjectScopedRequests(); stopJobPolling(); })' in script
    assert "storyJobTerminal" in script and "stopJobPolling();" in script


def test_primary_secondary_workspaces_reuse_the_shared_request_layer() -> None:
    revision = (ROOT / "web/static/revision-center.js").read_text(encoding="utf-8")
    planning = (ROOT / "web/static/planning-studio.js").read_text(encoding="utf-8")
    planning_control = [
        ROOT / "web/static/planning-control.js",
        ROOT / "web/static/planning-control/rolling-window.js",
        ROOT / "web/static/planning-control/rolling-lifecycle.js",
        ROOT / "web/static/planning-control/dependencies.js",
        ROOT / "web/static/planning-control/schedules.js",
    ]
    assert "window.storyosApiRequest(path, options)" in revision
    assert "window.storyosApiRequest(path,{method" in planning
    assert "fetch(path" not in revision
    for script_path in planning_control:
        script = script_path.read_text(encoding="utf-8")
        assert "window.storyosApiRequest(path" in script
        assert "fetch(path" not in script
