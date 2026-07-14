from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.project_context import get_project_context
from evaluation_engine import EvaluationService


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _project(root: Path) -> dict[str, Path]:
    protected = {
        "state": root / "data" / "state.json", "plan": root / "data" / "next_chapter_plan.json",
        "draft": root / "data" / "drafts" / "chapter_001_draft_v001.json", "characters": root / "data" / "characters.json",
    }
    _write(protected["state"], {"current_chapter": 1})
    _write(protected["plan"], {"chapter_id": 1, "chapter_goal": "推进线索"})
    _write(protected["draft"], {"chapter_id": 1, "draft_text": "主角在雨夜发现线索。", "generation": {}})
    _write(protected["characters"], {"characters": [{"name": "主角"}]})
    _write(root / "data" / "quality_reports" / "chapter_001_draft_v001_quality.json", {"chapter_id": 1, "source_type": "draft", "source_version": 1, "scores": {"continuity": .82, "pacing": .71, "hook_strength": .7, "readability": .85}, "flags": [{"type": "readability", "severity": "low", "message": "段落可略作拆分"}], "suggestions": ["保持场景焦点"], "reader_simulation": {"engagement_score": .73}})
    return protected


def test_evaluation_uses_existing_evidence_and_only_writes_evaluations(tmp_path: Path) -> None:
    protected = _project(tmp_path)
    before = {key: _hash(path) for key, path in protected.items()}
    service = EvaluationService(get_project_context(tmp_path))
    report, replayed = service.generate({"target_type": "chapter_draft", "chapter_number": 1, "operation_id": "eval-1"})
    assert replayed is False
    assert report["gate_status"] in {"pass", "attention"}
    assert len(report["dimensions"]) == 10
    assert report["overall_score"] is not None
    assert report["dimensions"][0]["score"] is None  # a plan alone is evidence, not a fabricated score
    assert (tmp_path / "data" / "evaluations" / "index.json").exists()
    assert before == {key: _hash(path) for key, path in protected.items()}
    replay, replayed = service.generate({"target_type": "chapter_draft", "chapter_number": 1, "operation_id": "eval-1"})
    assert replayed is True and replay["evaluation_id"] == report["evaluation_id"]


def test_evaluation_marks_report_stale_when_chapter_changes(tmp_path: Path) -> None:
    protected = _project(tmp_path)
    service = EvaluationService(get_project_context(tmp_path))
    report, _ = service.generate({"target_type": "chapter_draft", "chapter_number": 1})
    _write(protected["draft"], {"chapter_id": 1, "draft_text": "修改后的正文。", "generation": {}})
    assert service.detail(report["evaluation_id"])["status"] == "stale"
