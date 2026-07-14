from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_memory_repair_routes_and_chinese_actions_are_wired() -> None:
    routes = (ROOT / "web" / "routes.py").read_text(encoding="utf-8")
    script = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "/api/quality-reports/status" in routes
    assert "/api/quality-reports/repair" in routes
    assert "/api/vector-index/initialize" in routes
    assert "startMemoryRepair" in script
    assert "\\u751f\\u6210\\u5f53\\u524d\\u6b63\\u53f2\\u62a5\\u544a" in script
    assert "\\u521d\\u59cb\\u5316\\u672c\\u5730\\u7d22\\u5f15" in script
