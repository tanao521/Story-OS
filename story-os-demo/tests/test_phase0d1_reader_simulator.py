from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from core.contracts.reader_simulation import (
    ReaderSimulationRequest,
    SimulationMode,
    ResultState,
    StaleReason,
    to_public_score,
    score_level,
    retention_level,
)
from core.project_context import ProjectContext
from system.reader_simulator import ReaderSimulatorService, ReaderSimulatorError
from system.reader_simulation_store import ReaderSimulationStore


def _create_temp_project(tmp_path: Path) -> ProjectContext:
    from core.project_context import get_project_context
    project_root = tmp_path / "test_project"
    project_root.mkdir(parents=True)

    (project_root / "data").mkdir()
    (project_root / "data" / "chapters").mkdir()
    (project_root / "data" / "drafts").mkdir()
    (project_root / "data" / "manual").mkdir()
    (project_root / "data" / "edited").mkdir()
    (project_root / "data" / "summaries").mkdir()
    (project_root / "data" / "planning").mkdir()
    (project_root / "data" / "versions").mkdir()

    (project_root / "data" / "state.json").write_text(
        json.dumps({"current_chapter": 1, "project_id": "test-project", "timeline_id": "main"}),
        encoding="utf-8",
    )
    (project_root / "data" / "story_spec.json").write_text(
        json.dumps({"title": "Test Novel", "genre": "fantasy", "characters": {}}),
        encoding="utf-8",
    )
    (project_root / "data" / "planning" / "planning.json").write_text(
        json.dumps({
            "chapters": [
                {
                    "chapter_number": 1,
                    "chapter_goal": "主角踏上冒险",
                    "pacing_design": {"ending_hook": "神秘的声音"},
                }
            ]
        }),
        encoding="utf-8",
    )

    return get_project_context(project_root)


def _create_draft_version(ctx: ProjectContext, chapter_id: int, content: str) -> None:
    version = 1
    draft_dir = ctx.root / "data" / "drafts"
    draft_dir.mkdir(exist_ok=True)

    payload = {
        "chapter_id": chapter_id,
        "chapter_title": f"第{chapter_id}章",
        "draft_text": content,
        "created_at": datetime.now().isoformat(),
        "version": version,
        "version_label": f"draft_v{version:03d}",
    }

    json_path = draft_dir / f"chapter_{chapter_id:03d}_draft_v{version:03d}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    versions_index = {
        "version_index": "1.5",
        "chapter_id": chapter_id,
        "drafts": [
            {
                "source_type": "draft",
                "version": version,
                "version_label": f"draft_v{version:03d}",
                "json_path": json_path.as_posix(),
                "markdown_path": json_path.with_suffix(".md").as_posix(),
                "chapter_id": chapter_id,
                "chapter_title": f"第{chapter_id}章",
                "created_at": datetime.now().isoformat(),
                "actual_word_count": len(content),
                "mode": "test",
                "preview": content[:300],
            }
        ],
        "edited": [],
        "manual": [],
        "selected": {},
    }

    versions_dir = ctx.root / "data" / "versions"
    versions_dir.mkdir(exist_ok=True)
    versions_path = versions_dir / f"chapter_{chapter_id:03d}_versions.json"
    versions_path.write_text(json.dumps(versions_index, ensure_ascii=False), encoding="utf-8")


class TestContractAndDeterminism:
    def test_same_snapshot_produces_same_result(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。主角走进森林，听到神秘的声音。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)
        run2 = simulator.run_simulation(request)

        assert run1.status.value == "completed"
        assert run2.status.value == "completed"
        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.engagement_score.score == run2.result.engagement_score.score
        assert run1.result.retention_risk.score == run2.result.retention_risk.score

    def test_evaluator_version_is_persisted(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.result is not None
        assert run.result.evaluator_version == "reader-rule-v1"

    def test_all_scores_in_valid_range(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。主角走。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.result is not None
        assert 0.0 <= run.result.engagement_score.score <= 100.0
        assert 0.0 <= run.result.retention_risk.score <= 100.0
        assert 0.0 <= run.result.novel_health.overall_score <= 100.0
        assert 0.0 <= run.result.novel_health.pacing <= 100.0
        assert 0.0 <= run.result.novel_health.clarity <= 100.0
        assert 0.0 <= run.result.novel_health.continuity <= 100.0
        assert 0.0 <= run.result.novel_health.conflict <= 100.0
        assert 0.0 <= run.result.novel_health.payoff <= 100.0
        assert 0.0 <= run.result.novel_health.style_stability <= 100.0

    def test_score_scale_helper_functions(self) -> None:
        assert to_public_score(0.52) == 52.0
        assert to_public_score(0.0) == 0.0
        assert to_public_score(1.0) == 100.0
        assert to_public_score(0.85) == 85.0
        assert to_public_score(-0.1) == 0.0
        assert to_public_score(1.5) == 100.0

    def test_score_level_thresholds(self) -> None:
        assert score_level(90.0) == "excellent"
        assert score_level(85.0) == "excellent"
        assert score_level(80.0) == "good"
        assert score_level(70.0) == "good"
        assert score_level(60.0) == "fair"
        assert score_level(55.0) == "fair"
        assert score_level(50.0) == "poor"
        assert score_level(40.0) == "poor"
        assert score_level(30.0) == "critical"
        assert score_level(0.0) == "critical"

    def test_retention_level_thresholds(self) -> None:
        assert retention_level(20.0).value == "low"
        assert retention_level(30.0).value == "medium"
        assert retention_level(40.0).value == "medium"
        assert retention_level(50.0).value == "high"
        assert retention_level(70.0).value == "high"
        assert retention_level(75.0).value == "critical"
        assert retention_level(90.0).value == "critical"

    def test_deterministic_payload_stable(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。主角走进森林，听到神秘的声音。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)
        run2 = simulator.run_simulation(request)

        assert run1.result is not None
        assert run2.result is not None
        payload1 = run1.result.deterministic_payload()
        payload2 = run2.result.deterministic_payload()
        assert payload1 == payload2
        assert run1.result.deterministic_hash() == run2.result.deterministic_hash()

    def test_deterministic_payload_excludes_evaluated_at(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)
        time.sleep(0.1)
        run2 = simulator.run_simulation(request)

        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.evaluated_at != run2.result.evaluated_at
        assert run1.result.deterministic_hash() == run2.result.deterministic_hash()

    def test_all_enums_valid(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.result is not None
        level = run.result.retention_risk.level.value
        assert level in {"low", "medium", "high", "critical"}

        for flag in run.result.problem_flags:
            assert flag.severity.value in {"low", "medium", "high"}
            assert flag.category.value in {"content", "structure", "style", "continuity", "pacing", "character", "readability"}

    def test_missing_inputs_recorded(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        (ctx.root / "data" / "story_spec.json").unlink()
        (ctx.root / "data" / "planning" / "planning.json").unlink()

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert "story_spec" in run.snapshot.missing_inputs or "chapter_plan" in run.snapshot.missing_inputs

    def test_unknown_mode_rejected(self, tmp_path: Path) -> None:
        from enum import Enum

        ctx = _create_temp_project(tmp_path)

        class InvalidMode(Enum):
            RULE = "rule"
            LLM = "llm"

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=InvalidMode.LLM,
        )

        with pytest.raises(ReaderSimulatorError, match="Unsupported mode"):
            simulator.run_simulation(request)

    def test_no_model_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        model_called = {"value": False}

        def mock_generate(*args, **kwargs):
            model_called["value"] = True
            return ""

        monkeypatch.setattr("llm.model_gateway.ModelGateway.generate_text", mock_generate, raising=False)

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.status.value == "completed"
        assert not model_called["value"]


class TestSnapshotHashDeterminism:
    def test_same_inputs_same_context_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)
        run2 = simulator.run_simulation(request)

        assert run1.snapshot.context_hash == run2.snapshot.context_hash

    def test_source_content_change_changes_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)

        _create_draft_version(ctx, 1, "第一章修改后的内容。")
        run2 = simulator.run_simulation(request)

        assert run1.snapshot.context_hash != run2.snapshot.context_hash

    def test_chapter_plan_change_changes_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)

        planning_path = ctx.root / "data" / "planning" / "planning.json"
        planning_data = json.loads(planning_path.read_text(encoding="utf-8"))
        planning_data["chapters"][0]["chapter_goal"] = "新的目标"
        planning_path.write_text(json.dumps(planning_data, ensure_ascii=False), encoding="utf-8")

        run2 = simulator.run_simulation(request)
        assert run1.snapshot.context_hash != run2.snapshot.context_hash

    def test_summary_change_changes_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        summary_dir = ctx.root / "data" / "summaries"
        summary_dir.mkdir(exist_ok=True)
        (summary_dir / "chapter_001_summary.json").write_text(
            json.dumps({"summary": "原摘要", "chapter_id": 1}),
            encoding="utf-8",
        )

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)

        (summary_dir / "chapter_001_summary.json").write_text(
            json.dumps({"summary": "新摘要", "chapter_id": 1}),
            encoding="utf-8",
        )

        run2 = simulator.run_simulation(request)
        assert run1.snapshot.context_hash != run2.snapshot.context_hash

    def test_missing_inputs_change_changes_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        (ctx.root / "data" / "story_spec.json").unlink()

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)

        (ctx.root / "data" / "story_spec.json").write_text(
            json.dumps({"title": "Test Novel", "genre": "fantasy"}),
            encoding="utf-8",
        )

        run2 = simulator.run_simulation(request)
        assert run1.snapshot.context_hash != run2.snapshot.context_hash

    def test_context_hash_not_affected_by_absolute_path(self, tmp_path: Path) -> None:
        content = "第一章内容。主角走进森林。"

        project1 = tmp_path / "project1"
        project2 = tmp_path / "project2"

        for proj_root in [project1, project2]:
            proj_root.mkdir(parents=True)
            (proj_root / "data").mkdir()
            (proj_root / "data" / "chapters").mkdir()
            (proj_root / "data" / "drafts").mkdir()
            (proj_root / "data" / "manual").mkdir()
            (proj_root / "data" / "edited").mkdir()
            (proj_root / "data" / "summaries").mkdir()
            (proj_root / "data" / "planning").mkdir()
            (proj_root / "data" / "versions").mkdir()

            (proj_root / "data" / "state.json").write_text(
                json.dumps({"current_chapter": 1, "project_id": "test-project", "timeline_id": "main"}),
                encoding="utf-8",
            )
            (proj_root / "data" / "story_spec.json").write_text(
                json.dumps({"title": "Test Novel", "genre": "fantasy", "characters": {}}),
                encoding="utf-8",
            )
            (proj_root / "data" / "planning" / "planning.json").write_text(
                json.dumps({
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "chapter_goal": "主角踏上冒险",
                            "pacing_design": {"ending_hook": "神秘的声音"},
                        }
                    ]
                }),
                encoding="utf-8",
            )

            from core.project_context import get_project_context
            ctx = get_project_context(proj_root)
            _create_draft_version(ctx, 1, content)

        from core.project_context import get_project_context
        ctx1 = get_project_context(project1)
        ctx2 = get_project_context(project2)

        simulator1 = ReaderSimulatorService(ctx1)
        simulator2 = ReaderSimulatorService(ctx2)
        request1 = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        request2 = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator1.run_simulation(request1)
        run2 = simulator2.run_simulation(request2)

        assert run1.snapshot.context_hash == run2.snapshot.context_hash


class TestReadOnlySafety:
    def test_state_unchanged_after_simulation(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        state_before = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        simulator.run_simulation(request)

        state_after = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))
        assert state_before == state_after

    def test_current_chapter_unchanged(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        state_before = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        simulator.run_simulation(request)

        state_after = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))
        assert state_before["current_chapter"] == state_after["current_chapter"]

    def test_chapter_files_unchanged(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        chapter_path = ctx.root / "data" / "chapters" / "chapter_001.md"
        chapter_path.write_text("# 第1章\n\n原始内容。", encoding="utf-8")
        before_hash = hashlib.sha256(chapter_path.read_bytes()).hexdigest()

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        simulator.run_simulation(request)

        after_hash = hashlib.sha256(chapter_path.read_bytes()).hexdigest()
        assert before_hash == after_hash

    def test_only_simulation_artifact_created(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        before_files = set(ctx.root.rglob("*"))

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        after_files = set(ctx.root.rglob("*"))
        new_files = after_files - before_files

        assert len(new_files) >= 1
        for f in new_files:
            f_str = str(f)
            assert "simulator" in f_str or f.suffix == ".tmp"


class TestVersionResolution:
    def test_selected_version_priority(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "草稿内容。")

        manual_dir = ctx.root / "data" / "manual"
        manual_dir.mkdir(exist_ok=True)
        manual_payload = {
            "chapter_id": 1,
            "chapter_title": "第1章",
            "manual_text": "手动版本内容。",
            "created_at": datetime.now().isoformat(),
            "version": 1,
            "version_label": "manual_v001",
        }
        manual_path = manual_dir / "chapter_001_manual_v001.json"
        manual_path.write_text(json.dumps(manual_payload, ensure_ascii=False), encoding="utf-8")

        versions_index = {
            "version_index": "1.5",
            "chapter_id": 1,
            "drafts": [],
            "edited": [],
            "manual": [
                {
                    "source_type": "manual",
                    "version": 1,
                    "version_label": "manual_v001",
                    "json_path": manual_path.as_posix(),
                    "markdown_path": manual_path.with_suffix(".md").as_posix(),
                    "chapter_id": 1,
                    "chapter_title": "第1章",
                    "created_at": datetime.now().isoformat(),
                    "actual_word_count": len("手动版本内容。"),
                    "mode": "test",
                    "preview": "手动版本内容。",
                }
            ],
            "selected": {"source_type": "manual", "version": 1},
        }
        versions_dir = ctx.root / "data" / "versions"
        versions_path = versions_dir / "chapter_001_versions.json"
        versions_path.write_text(json.dumps(versions_index, ensure_ascii=False), encoding="utf-8")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.snapshot.source.source_type == "manual"

    def test_manual_priority_over_edited(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)

        edited_dir = ctx.root / "data" / "edited"
        edited_dir.mkdir(exist_ok=True)
        edited_payload = {
            "chapter_id": 1,
            "chapter_title": "第1章",
            "edited_text": "编辑版本内容。",
            "created_at": datetime.now().isoformat(),
            "version": 1,
            "version_label": "edited_v001",
        }
        edited_path = edited_dir / "chapter_001_edited_v001.json"
        edited_path.write_text(json.dumps(edited_payload, ensure_ascii=False), encoding="utf-8")

        manual_dir = ctx.root / "data" / "manual"
        manual_dir.mkdir(exist_ok=True)
        manual_payload = {
            "chapter_id": 1,
            "chapter_title": "第1章",
            "manual_text": "手动版本内容。",
            "created_at": datetime.now().isoformat(),
            "version": 1,
            "version_label": "manual_v001",
        }
        manual_path = manual_dir / "chapter_001_manual_v001.json"
        manual_path.write_text(json.dumps(manual_payload, ensure_ascii=False), encoding="utf-8")

        versions_index = {
            "version_index": "1.5",
            "chapter_id": 1,
            "drafts": [],
            "edited": [
                {
                    "source_type": "edited",
                    "version": 1,
                    "version_label": "edited_v001",
                    "json_path": edited_path.as_posix(),
                    "markdown_path": edited_path.with_suffix(".md").as_posix(),
                    "chapter_id": 1,
                    "chapter_title": "第1章",
                    "created_at": datetime.now().isoformat(),
                    "actual_word_count": len("编辑版本内容。"),
                    "mode": "test",
                    "preview": "编辑版本内容。",
                }
            ],
            "manual": [
                {
                    "source_type": "manual",
                    "version": 1,
                    "version_label": "manual_v001",
                    "json_path": manual_path.as_posix(),
                    "markdown_path": manual_path.with_suffix(".md").as_posix(),
                    "chapter_id": 1,
                    "chapter_title": "第1章",
                    "created_at": datetime.now().isoformat(),
                    "actual_word_count": len("手动版本内容。"),
                    "mode": "test",
                    "preview": "手动版本内容。",
                }
            ],
            "selected": {},
        }
        versions_dir = ctx.root / "data" / "versions"
        versions_path = versions_dir / "chapter_001_versions.json"
        versions_path.write_text(json.dumps(versions_index, ensure_ascii=False), encoding="utf-8")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.snapshot.source.source_type == "manual"

    def test_specific_version_id_used(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "草稿内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            source_version_id="draft_v001",
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        assert run.snapshot.source.source_version_id == "draft_v001"
        assert run.snapshot.source.source_type == "draft"

    def test_nonexistent_version_rejected(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "草稿内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            source_version_id="draft_v999",
            mode=SimulationMode.RULE,
        )

        run = simulator.run_simulation(request)
        assert run.status.value == "failed"


class TestContextBoundaries:
    def test_recent_chapters_limit_3(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)

        for i in range(1, 6):
            _create_draft_version(ctx, i, f"第{i}章内容。")
            summary_dir = ctx.root / "data" / "summaries"
            summary_dir.mkdir(exist_ok=True)
            summary_path = summary_dir / f"chapter_{i:03d}_summary.json"
            summary_path.write_text(json.dumps({"summary": f"第{i}章摘要。"}), encoding="utf-8")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=5,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        recent_chapters = run.snapshot.context_refs.get("recent_chapters", [])
        assert len(recent_chapters) <= 3

    def test_old_chapters_only_via_summary(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)

        for i in range(1, 6):
            _create_draft_version(ctx, i, f"第{i}章内容。")
            summary_dir = ctx.root / "data" / "summaries"
            summary_dir.mkdir(exist_ok=True)
            summary_path = summary_dir / f"chapter_{i:03d}_summary.json"
            summary_path.write_text(json.dumps({"summary": f"第{i}章摘要。"}), encoding="utf-8")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=5,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)

        recent_summaries = run.snapshot.context_refs.get("recent_summaries", [])
        assert len(recent_summaries) <= 3

    def test_context_hash_stable(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )

        run1 = simulator.run_simulation(request)
        run2 = simulator.run_simulation(request)

        assert run1.snapshot.context_hash == run2.snapshot.context_hash


class TestProjectIsolation:
    def test_two_projects_isolated(self, tmp_path: Path) -> None:
        ctx1 = _create_temp_project(tmp_path / "project1")
        ctx2 = _create_temp_project(tmp_path / "project2")

        _create_draft_version(ctx1, 1, "项目1内容。")
        _create_draft_version(ctx2, 1, "项目2内容。")

        simulator1 = ReaderSimulatorService(ctx1)
        request1 = ReaderSimulationRequest(
            project_id="project1",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run1 = simulator1.run_simulation(request1)

        simulator2 = ReaderSimulatorService(ctx2)
        request2 = ReaderSimulationRequest(
            project_id="project2",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run2 = simulator2.run_simulation(request2)

        assert run1.snapshot.project_id == "project1"
        assert run2.snapshot.project_id == "project2"
        assert run1.snapshot.source.source_hash != run2.snapshot.source.source_hash

    def test_run_records_isolated(self, tmp_path: Path) -> None:
        ctx1 = _create_temp_project(tmp_path / "project1")
        ctx2 = _create_temp_project(tmp_path / "project2")

        _create_draft_version(ctx1, 1, "项目1内容。")
        _create_draft_version(ctx2, 1, "项目2内容。")

        simulator1 = ReaderSimulatorService(ctx1)
        request1 = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run1 = simulator1.run_simulation(request1)
        store1 = ReaderSimulationStore(ctx1)
        store1.save_run(run1)

        store2 = ReaderSimulationStore(ctx2)
        runs2 = store2.list_runs()
        assert len(runs2) == 0


class TestHistoricalResultStates:
    def test_result_current_when_source_unchanged(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        staleness = store.check_run_staleness(run.run_id)
        assert staleness.state == ResultState.CURRENT
        assert staleness.stale_reasons == []

    def test_result_stale_when_source_changed(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        _create_draft_version(ctx, 1, "第一章修改后的内容。")

        staleness = store.check_run_staleness(run.run_id)
        assert staleness.state == ResultState.STALE
        assert StaleReason.SOURCE_CHANGED in staleness.stale_reasons

    def test_result_stale_when_context_changed(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        summary_path = ctx.root / "data" / "summaries" / "chapter_001_summary.json"
        summary_path.write_text(
            json.dumps({"summary": "主角踏上了冒险之旅。", "chapter_id": 1}),
            encoding="utf-8",
        )

        staleness = store.check_run_staleness(run.run_id)
        assert staleness.state == ResultState.STALE
        assert StaleReason.CONTEXT_CHANGED in staleness.stale_reasons

    def test_result_stale_when_both_source_and_context_changed(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        _create_draft_version(ctx, 1, "第一章修改后的内容。")
        summary_path = ctx.root / "data" / "summaries" / "chapter_001_summary.json"
        summary_path.write_text(
            json.dumps({"summary": "新的摘要。", "chapter_id": 1}),
            encoding="utf-8",
        )

        staleness = store.check_run_staleness(run.run_id)
        assert staleness.state == ResultState.STALE
        reason_values = {r.value for r in staleness.stale_reasons}
        assert "source_changed" in reason_values
        assert "context_changed" in reason_values

    def test_result_source_missing_when_version_deleted(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        draft_path = ctx.root / "data" / "drafts" / "chapter_001_draft_v001.json"
        draft_path.unlink()

        staleness = store.check_run_staleness(run.run_id)
        assert staleness.state == ResultState.SOURCE_MISSING

    def test_stale_run_not_deleted(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)
        run_id = run.run_id

        _create_draft_version(ctx, 1, "第一章修改后的内容。")

        loaded = store.load_run(run_id)
        assert loaded is not None

    def test_staleness_check_is_read_only(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        simulator = ReaderSimulatorService(ctx)
        store = ReaderSimulationStore(ctx)
        request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        run = simulator.run_simulation(request)
        store.save_run(run)

        runs_before = list(store.runs_dir.glob("*.json"))
        store.check_run_staleness(run.run_id)
        runs_after = list(store.runs_dir.glob("*.json"))
        assert len(runs_before) == len(runs_after)


class TestCLI:
    def test_simulate_reader_cli(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。主角走。")

        result = subprocess.run(
            ["python", "main.py", "simulate-reader", "--chapter", "1", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "第1章读者模拟完成" in result.stdout

    def test_simulate_reader_cli_help(self) -> None:
        result = subprocess.run(
            ["python", "main.py", "simulate-reader", "--help"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--chapter" in result.stdout

    def test_list_reader_simulations_cli(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        subprocess.run(
            ["python", "main.py", "simulate-reader", "--chapter", "1", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            ["python", "main.py", "list-reader-simulations", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "1 条读者模拟记录" in result.stdout

    def test_nonexistent_chapter_returns_nonzero(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)

        result = subprocess.run(
            ["python", "main.py", "simulate-reader", "--chapter", "999", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1

    def test_cli_no_absolute_paths(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        result = subprocess.run(
            ["python", "main.py", "simulate-reader", "--chapter", "1", "--project-root", str(ctx.root), "--json"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        root_str = str(ctx.root)
        assert root_str not in result.stdout
        assert root_str.replace("\\", "/") not in result.stdout


class TestWebAPI:
    def test_run_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.post("/api/simulator/reader/run", json={"chapter_id": 1, "project_root": str(ctx.root)})
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert "run_id" in data["result"]
            assert "engagement_score" in data["result"]

    def test_list_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.post("/api/simulator/reader/run", json={"chapter_id": 1, "project_root": str(ctx.root)})

            response = client.get(f"/api/simulator/reader/runs?project_root={str(ctx.root)}")
            assert response.status_code == 200
            data = response.json()
            assert len(data["result"]["simulations"]) >= 1

    def test_detail_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            run_response = client.post("/api/simulator/reader/run", json={"chapter_id": 1, "project_root": str(ctx.root)})
            run_id = run_response.json()["result"]["run_id"]

            response = client.get(f"/api/simulator/reader/runs/{run_id}?project_root={str(ctx.root)}")
            assert response.status_code == 200
            data = response.json()
            assert data["result"]["run_id"] == run_id

    def test_nonexistent_run_returns_404(self) -> None:
        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/simulator/reader/runs/nonexistent-run-id")
            assert response.status_code == 404

    def test_api_no_absolute_paths(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            run_response = client.post("/api/simulator/reader/run", json={"chapter_id": 1, "project_root": str(ctx.root)})
            assert run_response.status_code == 200
            run_data_str = json.dumps(run_response.json())
            assert str(ctx.root) not in run_data_str
            assert str(ctx.root).replace("\\", "/") not in run_data_str

            run_id = run_response.json()["result"]["run_id"]

            list_response = client.get(f"/api/simulator/reader/runs?project_root={str(ctx.root)}")
            assert list_response.status_code == 200
            list_data_str = json.dumps(list_response.json())
            assert str(ctx.root) not in list_data_str
            assert str(ctx.root).replace("\\", "/") not in list_data_str

            detail_response = client.get(f"/api/simulator/reader/runs/{run_id}?project_root={str(ctx.root)}")
            assert detail_response.status_code == 200
            detail_data_str = json.dumps(detail_response.json())
            assert str(ctx.root) not in detail_data_str
            assert str(ctx.root).replace("\\", "/") not in detail_data_str


class TestStaticGuards:
    def test_no_os_chdir_in_simulator(self) -> None:
        import ast

        with open("system/reader_simulator.py", "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "chdir":
                assert False, "reader_simulator.py contains os.chdir call"

    def test_no_commit_calls_in_simulator(self) -> None:
        import ast

        with open("system/reader_simulator.py", "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"commit_chapter", "commit", "apply_revision"}:
                    assert False, f"reader_simulator.py contains {node.func.id} call"

    def test_no_raw_path_data(self) -> None:
        import ast

        with open("system/reader_simulator.py", "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "data/" in node.value
            ):
                if "data/simulator/reader_runs" not in node.value:
                    assert False, f"reader_simulator.py contains raw Path('data/...'): {node.value}"
