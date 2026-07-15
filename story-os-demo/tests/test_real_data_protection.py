from __future__ import annotations

from pathlib import Path

import pytest


def test_temporary_project_writes_remain_allowed(tmp_path: Path) -> None:
    target = tmp_path / "data" / "story_blueprint.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "{}"


def test_checked_out_project_data_write_is_blocked() -> None:
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(RuntimeError, match="TEST_REAL_DATA_WRITE_BLOCKED"):
        (root / "data" / "story_blueprint.json").write_text("must not be written", encoding="utf-8")
