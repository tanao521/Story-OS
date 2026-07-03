from __future__ import annotations

import json
from pathlib import Path

from system.status_dashboard import (
    build_status_dashboard,
    load_latest_memory_health_summary,
    render_status_text,
)


def test_memory_health_missing_report_returns_exists_false(tmp_path: Path) -> None:
    summary = load_latest_memory_health_summary(tmp_path)
    assert summary == {"exists": False}


def test_status_json_contains_memory_health_summary(tmp_path: Path) -> None:
    health_dir = tmp_path / "health"
    health_dir.mkdir()
    (health_dir / "latest_memory_health.json").write_text(
        json.dumps(
            {
                "overall_status": "warning",
                "overall_score": 0.86,
                "checked_at": "2026-07-02T16:00:00",
                "summary": {"errors": 0, "warnings": 3, "infos": 8},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    status = build_status_dashboard(tmp_path)

    assert status["memory_health"]["exists"] is True
    assert status["memory_health"]["overall_status"] == "warning"
    assert status["memory_health"]["overall_score"] == 0.86
    assert status["memory_health"]["warnings"] == 3


def test_status_text_contains_memory_health(tmp_path: Path) -> None:
    status = build_status_dashboard(tmp_path)
    output = render_status_text(status)

    assert "记忆健康" in output
    assert "Traceback" not in output
    assert "API Key" not in output
