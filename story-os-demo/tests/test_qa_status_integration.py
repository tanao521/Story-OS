from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import main
from system.obsidian_sync import OBSIDIAN_DIRS, sync_to_obsidian
from system.status_dashboard import build_status_dashboard
from system.story_qa import save_qa_log, search_vector_memory_if_available


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path) -> None:
    write_json(root / "data" / "story_spec.json", {"title": "QA Novel"})
    write_json(root / "data" / "story_blueprint.json", {"title": "QA Novel"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"core_rules": []})
    write_json(root / "data" / "state.json", {"current_chapter": 1})


def test_status_counts_qa_logs(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    save_qa_log({
        "qa_version": "1.9",
        "question": "q",
        "answer": "a",
        "mode": "state",
        "confidence": "high",
        "sources": [],
        "related": {"chapters": [], "characters": [], "foreshadows": [], "todos": [], "quality_reports": []},
        "warnings": [],
    }, tmp_path / "data")

    status = build_status_dashboard(tmp_path / "data")

    assert status["qa"]["logs_count"] == 1
    assert status["qa"]["latest_log_path"]


def test_obsidian_dirs_include_qa_logs() -> None:
    assert "14_QA_Logs" in OBSIDIAN_DIRS


def test_sync_obsidian_copies_qa_logs(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    qa_dir = tmp_path / "data" / "qa_logs"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_20260101_000000.md").write_text("# Story OS 问答记录", encoding="utf-8")

    sync_to_obsidian(tmp_path / "data", tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "14_QA_Logs" / "qa_20260101_000000.md").exists()


def test_ask_state_json_outputs_pure_json(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["main.py", "ask-state", "现在第几章？", "--json", "--no-log"])

    main.main()
    output = capsys.readouterr().out

    parsed = json.loads(output)
    assert parsed["qa_version"] == "1.9"
    assert parsed["mode"] == "state"


def test_ask_memory_no_vector_does_not_call_vector(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    called = {"value": False}

    def fake_vector(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        called["value"] = True
        return []

    monkeypatch.setattr("system.story_qa.search_vector_memory_if_available", fake_vector)
    monkeypatch.setattr(sys, "argv", ["main.py", "ask-memory", "铁门出现过吗？", "--no-vector", "--json", "--no-log"])

    main.main()
    json.loads(capsys.readouterr().out)

    assert called["value"] is False


def test_search_vector_memory_disabled_returns_empty(tmp_path: Path) -> None:
    prepare_project(tmp_path)

    assert search_vector_memory_if_available("问题", tmp_path / "data") == []
