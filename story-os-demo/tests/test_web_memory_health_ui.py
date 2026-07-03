from __future__ import annotations

from pathlib import Path


def text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_memory_health_ui_static_assets_present() -> None:
    html = text("web/templates/index.html")
    js = text("web/static/app.js")
    css = text("web/static/style.css")

    assert "记忆健康" in html
    assert "memoryHealthPanel" in html
    assert "runMemoryHealth" in js
    assert "renderMemoryHealth" in js
    assert "/api/memory-health" in js
    assert ".health-panel" in css
    assert ".health-status-warning" in css


def test_memory_health_ui_uses_no_external_cdn() -> None:
    combined = "\n".join([
        text("web/templates/index.html"),
        text("web/static/app.js"),
        text("web/static/style.css"),
    ])

    assert "cdn." not in combined.lower()
    assert "unpkg.com" not in combined.lower()
    assert "jsdelivr" not in combined.lower()
