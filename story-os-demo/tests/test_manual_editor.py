from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.manual_editor import create_manual_version, is_valid_manual_text, render_manual_markdown


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prose() -> str:
    base = (
        "风从避难所的铁门缝里挤进来，带着潮湿的灰尘。林岚把手电压低，听见墙后传来细小的敲击声。"
        "她没有立刻说话，只把那张旧地图折进袖口，示意同伴退到阴影里。"
        "远处的警报像被水泡坏的钟，一声慢过一声。有人在门外喊她的名字，声音却不是任何熟人。"
        "她终于明白，昨夜失踪的巡逻队并不是离开了这里，而是被某种东西学会了说话。"
    )
    return base * 2


def test_is_valid_manual_text_rejects_empty() -> None:
    valid, warnings = is_valid_manual_text("")

    assert valid is False
    assert warnings


def test_is_valid_manual_text_accepts_prose() -> None:
    valid, warnings = is_valid_manual_text(prose(), min_chars=50)

    assert valid is True
    assert warnings == []


def test_create_manual_version_increments_and_keeps_state(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "state.json", {"current_chapter": 0})
    write_json(
        tmp_path / "data" / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": prose(),
            "editing": {"mode": "deepseek", "fallback_used": False},
        },
    )

    first = create_manual_version(1, "edited", 1, prose(), tmp_path / "data")
    second = create_manual_version(1, "edited", 1, prose() + "她把门闩重新扣紧。", tmp_path / "data")
    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))

    assert first["version_label"] == "manual_v001"
    assert second["version_label"] == "manual_v002"
    assert state["current_chapter"] == 0
    assert (tmp_path / "data" / "manual" / "chapter_001_manual_v001.json").exists()
    assert (tmp_path / "data" / "manual" / "chapter_001_manual.json").exists()


def test_render_manual_markdown_mentions_manual_version() -> None:
    markdown = render_manual_markdown(
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version_label": "manual_v001",
            "source_type": "edited",
            "source_version": 1,
            "manual_text": prose(),
            "checks": {"valid_text": True, "warnings": []},
        }
    )

    assert "人工修改版" in markdown
    assert "manual_v001" in markdown
