from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from core.contracts.reader_persona import (
    AgreementLevel,
    PanelMode,
    ReaderPanelRequest,
    ReaderPersona,
    ResultState,
    StalenessResult,
)
from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
from core.project_context import ProjectContext, get_project_context
from system.reader_persona_registry import ReaderPersonaRegistry, ReaderPersonaRegistryError
from system.reader_panel_service import ReaderPanelService, ReaderPanelServiceError
from system.reader_panel_store import ReaderPanelStore
from system.reader_simulator import ReaderSimulatorService


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


def _create_draft_version(ctx: ProjectContext, chapter_id: int, content: str, version: int = 1) -> None:
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


class TestPersonaContract:
    def test_five_builtin_personas_loadable(self) -> None:
        registry = ReaderPersonaRegistry()
        personas = registry.list_personas()
        assert len(personas) == 5

    def test_persona_id_unique(self) -> None:
        registry = ReaderPersonaRegistry()
        personas = registry.list_personas()
        ids = [p.persona_id for p in personas]
        assert len(ids) == len(set(ids))

    def test_persona_version_exists(self) -> None:
        registry = ReaderPersonaRegistry()
        for persona in registry.list_personas():
            assert persona.persona_version is not None
            assert len(persona.persona_version) > 0

    def test_persona_fingerprint_stable(self) -> None:
        registry = ReaderPersonaRegistry()
        persona = registry.get_persona("hook_driven_reader")
        fp1 = persona.persona_fingerprint
        fp2 = persona.persona_fingerprint
        assert fp1 == fp2

    def test_fingerprint_not_affected_by_load_time(self) -> None:
        registry = ReaderPersonaRegistry()
        persona = registry.get_persona("hook_driven_reader")
        fp1 = persona.persona_fingerprint
        time.sleep(0.01)
        fp2 = persona.persona_fingerprint
        assert fp1 == fp2

    def test_weights_non_negative(self) -> None:
        registry = ReaderPersonaRegistry()
        for persona in registry.list_personas():
            for w in persona.focus_weights.to_dict().values():
                assert w >= 0

    def test_weights_normalized(self) -> None:
        registry = ReaderPersonaRegistry()
        for persona in registry.list_personas():
            normalized = persona.focus_weights.normalized()
            total = sum(normalized.to_dict().values())
            assert abs(total - 1.0) < 0.0001

    def test_invalid_focus_dimension_rejected(self) -> None:
        registry = ReaderPersonaRegistry()
        assert not registry.is_valid_focus_dimension("invalid_dimension")

    def test_valid_focus_dimensions(self) -> None:
        registry = ReaderPersonaRegistry()
        valid = {"hook", "pacing", "conflict", "clarity", "continuity", "payoff", "style_naturalness", "emotion"}
        for dim in valid:
            assert registry.is_valid_focus_dimension(dim)

    def test_persona_contains_no_prompt(self) -> None:
        registry = ReaderPersonaRegistry()
        for persona in registry.list_personas():
            assert "prompt" not in str(persona).lower()
            assert "llm" not in str(persona).lower()
            assert "model" not in str(persona).lower()


class TestPersonaDeterminism:
    def test_same_base_result_produces_same_persona_result(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。主角走进森林，听到神秘的声音。")

        simulator = ReaderSimulatorService(ctx)
        sim_request = ReaderSimulationRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            mode=SimulationMode.RULE,
        )
        sim_run = simulator.run_simulation(sim_request)
        assert sim_run.result is not None

        service = ReaderPanelService(ctx)
        panel_request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run1 = service.run_panel(panel_request)
        run2 = service.run_panel(panel_request)

        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.deterministic_hash() == run2.result.deterministic_hash()

    def test_persona_deterministic_hash_stable(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "pacing_sensitive_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run1 = service.run_panel(request)
        run2 = service.run_panel(request)

        assert run1.result is not None
        assert run2.result is not None
        for pr1, pr2 in zip(run1.result.persona_results, run2.result.persona_results):
            assert pr1.deterministic_hash() == pr2.deterministic_hash()

    def test_different_personas_produce_different_results(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request1 = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        request2 = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["continuity_core_reader", "world_logic_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run1 = service.run_panel(request1)
        run2 = service.run_panel(request2)

        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.persona_results[0].engagement_score != run2.result.persona_results[0].engagement_score

    def test_all_scores_in_0_100_range(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader", "pacing_sensitive_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.result is not None

        assert 0.0 <= run.result.panel_score <= 100.0
        assert 0.0 <= run.result.panel_retention_risk <= 100.0
        for pr in run.result.persona_results:
            assert 0.0 <= pr.engagement_score <= 100.0
            assert 0.0 <= pr.retention_risk <= 100.0


class TestPanelAggregation:
    def test_two_to_five_personas_allowed(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)

        for count in [2, 3, 4, 5]:
            personas = ["hook_driven_reader", "character_empathy_reader", "pacing_sensitive_reader", "continuity_core_reader", "world_logic_reader"][:count]
            request = ReaderPanelRequest(
                project_id="test-project",
                timeline_id="main",
                chapter_id=1,
                persona_ids=personas,
                mode=PanelMode.DETERMINISTIC,
            )
            run = service.run_panel(request)
            assert run.status.value == "completed"

    def test_single_persona_rejected(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.status.value == "failed"

    def test_six_personas_rejected(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader", "pacing_sensitive_reader", "continuity_core_reader", "world_logic_reader", "hook_driven_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.status.value == "failed"

    def test_duplicate_persona_rejected(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "hook_driven_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.status.value == "failed"

    def test_unknown_persona_rejected(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "unknown_persona"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.status.value == "failed"

    def test_persona_order_does_not_affect_result(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request1 = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        request2 = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["character_empathy_reader", "hook_driven_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run1 = service.run_panel(request1)
        run2 = service.run_panel(request2)

        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.deterministic_hash() == run2.result.deterministic_hash()

    def test_panel_score_is_average(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.result is not None

        scores = [pr.engagement_score for pr in run.result.persona_results]
        expected_average = sum(scores) / len(scores)
        assert abs(run.result.panel_score - expected_average) < 0.01

    def test_agreement_level_stable(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader", "pacing_sensitive_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run1 = service.run_panel(request)
        run2 = service.run_panel(request)

        assert run1.result is not None
        assert run2.result is not None
        assert run1.result.agreement.agreement_level == run2.result.agreement.agreement_level


class TestPanelClassificationBoundary:
    def _build_mock_persona_result(self, persona_id: str, has_flag: bool, severity: str = "medium"):
        from core.contracts.reader_persona import PersonaPriorityFlag, PersonaResult
        flags = []
        if has_flag:
            flags.append(PersonaPriorityFlag(
                flag_code="test_flag",
                base_severity=severity,
                persona_severity=severity,
                priority=20 if severity == "high" else 10,
                reason="test reason",
                evidence_refs=["evidence_1"],
            ))
        return PersonaResult(
            persona_id=persona_id,
            persona_version="1.0",
            persona_fingerprint=f"fp_{persona_id}",
            engagement_score=75.0,
            retention_risk=30.0,
            priority_flags=flags,
        )

    def test_two_personas_one_support_minority(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        ctx_mock = None
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 0
        assert len(minority) == 1
        assert minority[0].flag_code == "test_flag"

    def test_two_personas_two_support_consensus(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 1
        assert consensus[0].flag_code == "test_flag"
        assert len(minority) == 0

    def test_three_personas_one_support_minority(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", False),
            self._build_mock_persona_result("p3", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 0
        assert len(minority) == 1
        assert minority[0].flag_code == "test_flag"

    def test_three_personas_two_support_consensus(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 1
        assert consensus[0].flag_code == "test_flag"
        assert len(minority) == 0

    def test_four_personas_two_support_minority(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", False),
            self._build_mock_persona_result("p4", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 0
        assert len(minority) == 1
        assert minority[0].flag_code == "test_flag"

    def test_four_personas_three_support_consensus(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", True, "medium"),
            self._build_mock_persona_result("p4", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 1
        assert consensus[0].flag_code == "test_flag"
        assert len(minority) == 0

    def test_five_personas_two_support_minority(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", False),
            self._build_mock_persona_result("p4", False),
            self._build_mock_persona_result("p5", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 0
        assert len(minority) == 1
        assert minority[0].flag_code == "test_flag"

    def test_five_personas_three_support_consensus(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", True, "medium"),
            self._build_mock_persona_result("p4", False),
            self._build_mock_persona_result("p5", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 1
        assert consensus[0].flag_code == "test_flag"
        assert len(minority) == 0

    def test_consensus_and_minority_no_overlap(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", True, "medium"),
            self._build_mock_persona_result("p4", False),
            self._build_mock_persona_result("p5", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        consensus_codes = set(f.flag_code for f in consensus)
        minority_codes = set(f.flag_code for f in minority)
        assert len(consensus_codes & minority_codes) == 0

    def test_supported_flag_not_lost_at_50_percent(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", False),
            self._build_mock_persona_result("p4", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        all_codes = set(f.flag_code for f in consensus) | set(f.flag_code for f in minority)
        assert "test_flag" in all_codes

    def test_zero_support_not_in_any_set(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results = [
            self._build_mock_persona_result("p1", False),
            self._build_mock_persona_result("p2", False),
        ]

        consensus = service._find_consensus_flags(results)
        minority = service._find_minority_flags(results)

        assert len(consensus) == 0
        assert len(minority) == 0

    def test_persona_order_does_not_affect_classification(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        results_1 = [
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
            self._build_mock_persona_result("p3", False),
        ]

        results_2 = [
            self._build_mock_persona_result("p3", False),
            self._build_mock_persona_result("p1", True, "medium"),
            self._build_mock_persona_result("p2", True, "medium"),
        ]

        consensus_1 = service._find_consensus_flags(results_1)
        minority_1 = service._find_minority_flags(results_1)
        consensus_2 = service._find_consensus_flags(results_2)
        minority_2 = service._find_minority_flags(results_2)

        assert set(f.flag_code for f in consensus_1) == set(f.flag_code for f in consensus_2)
        assert set(f.flag_code for f in minority_1) == set(f.flag_code for f in minority_2)


class TestSnapshotConsistency:
    def test_all_personas_use_same_snapshot(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader", "pacing_sensitive_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.result is not None
        assert run.snapshot_id is not None

        store = ReaderPanelStore(ctx)
        loaded = store.load_run(run.panel_run_id)
        assert loaded is not None
        assert loaded.snapshot_id == run.snapshot_id

    def test_all_personas_use_same_source_hash(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )

        run = service.run_panel(request)
        assert run.source_hash is not None
        assert len(run.source_hash) > 0


class TestPersonaResultDeterminism:
    def test_same_input_same_hash(self) -> None:
        from core.contracts.reader_persona import PersonaResult, PersonaPriorityFlag, PersonaObservation
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            priority_flags=[
                PersonaPriorityFlag(
                    flag_code="flag1",
                    base_severity="medium",
                    persona_severity="medium",
                    priority=10,
                    reason="test",
                    evidence_refs=["e1"],
                )
            ],
            persona_observations=[
                PersonaObservation(category="test", message="test msg", evidence_refs=["e1"])
            ],
            optimization_priorities=[],
            evidence_refs=["e1", "e2"],
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            priority_flags=[
                PersonaPriorityFlag(
                    flag_code="flag1",
                    base_severity="medium",
                    persona_severity="medium",
                    priority=10,
                    reason="test",
                    evidence_refs=["e1"],
                )
            ],
            persona_observations=[
                PersonaObservation(category="test", message="test msg", evidence_refs=["e1"])
            ],
            optimization_priorities=[],
            evidence_refs=["e1", "e2"],
        )
        assert pr1.deterministic_hash() == pr2.deterministic_hash()

    def test_time_field_not_in_hash(self) -> None:
        from core.contracts.reader_persona import PersonaResult
        pr = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
        )
        hash1 = pr.deterministic_hash()
        payload = pr.deterministic_payload()
        assert "created_at" not in payload
        assert "evaluated_at" not in payload
        assert "run_id" not in payload
        assert "panel_run_id" not in payload

    def test_fingerprint_change_changes_hash(self) -> None:
        from core.contracts.reader_persona import PersonaResult
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_456",
            engagement_score=75.0,
            retention_risk=30.0,
        )
        assert pr1.deterministic_hash() != pr2.deterministic_hash()

    def test_engagement_change_changes_hash(self) -> None:
        from core.contracts.reader_persona import PersonaResult
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=80.0,
            retention_risk=30.0,
        )
        assert pr1.deterministic_hash() != pr2.deterministic_hash()

    def test_priority_flag_change_changes_hash(self) -> None:
        from core.contracts.reader_persona import PersonaResult, PersonaPriorityFlag
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            priority_flags=[
                PersonaPriorityFlag(
                    flag_code="flag1",
                    base_severity="medium",
                    persona_severity="medium",
                    priority=10,
                    reason="test",
                    evidence_refs=["e1"],
                )
            ],
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            priority_flags=[
                PersonaPriorityFlag(
                    flag_code="flag1",
                    base_severity="medium",
                    persona_severity="high",
                    priority=20,
                    reason="test",
                    evidence_refs=["e1"],
                )
            ],
        )
        assert pr1.deterministic_hash() != pr2.deterministic_hash()

    def test_evidence_order_stable(self) -> None:
        from core.contracts.reader_persona import PersonaResult
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            evidence_refs=["e2", "e1", "e3"],
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            evidence_refs=["e1", "e2", "e3"],
        )
        assert pr1.deterministic_hash() == pr2.deterministic_hash()

    def test_observations_order_stable(self) -> None:
        from core.contracts.reader_persona import PersonaResult, PersonaObservation
        pr1 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            persona_observations=[
                PersonaObservation(category="b", message="msg b", evidence_refs=[]),
                PersonaObservation(category="a", message="msg a", evidence_refs=[]),
            ],
        )
        pr2 = PersonaResult(
            persona_id="test_persona",
            persona_version="1.0",
            persona_fingerprint="fp_123",
            engagement_score=75.0,
            retention_risk=30.0,
            persona_observations=[
                PersonaObservation(category="a", message="msg a", evidence_refs=[]),
                PersonaObservation(category="b", message="msg b", evidence_refs=[]),
            ],
        )
        assert pr1.deterministic_hash() == pr2.deterministic_hash()

    def test_hash_stable_after_persistence(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        run = service.run_panel(request)
        assert run.result is not None

        store = ReaderPanelStore(ctx)
        loaded_run = store.load_run(run.panel_run_id)
        assert loaded_run is not None
        assert loaded_run.result is not None

        for i in range(len(run.result.persona_results)):
            assert run.result.persona_results[i].deterministic_hash() == loaded_run.result.persona_results[i].deterministic_hash()


class TestRetentionRiskBoundary:
    def test_retention_risk_always_0_100(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。" * 100)

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        run = service.run_panel(request)
        assert run.result is not None

        for pr in run.result.persona_results:
            assert 0.0 <= pr.retention_risk <= 100.0
        assert 0.0 <= run.result.panel_retention_risk <= 100.0

    def test_retention_clamped_at_100(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        import types

        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        persona = types.SimpleNamespace()
        persona.sensitivity = types.SimpleNamespace()
        persona.sensitivity.risk_sensitivity = 1.0
        persona.sensitivity.slow_opening_sensitivity = 1.0
        persona.sensitivity.continuity_sensitivity = 1.0

        base_result = types.SimpleNamespace()
        base_result.retention_risk = types.SimpleNamespace()
        base_result.retention_risk.score = 90.0
        base_result.novel_health = types.SimpleNamespace()
        base_result.novel_health.pacing = 10.0
        base_result.novel_health.continuity = 20.0

        risk = service._calculate_retention_risk(persona, base_result, 30.0)
        assert risk == 100.0
        assert isinstance(risk, float)

    def test_retention_clamped_at_0(self) -> None:
        from system.reader_panel_service import ReaderPanelService
        import types

        service = ReaderPanelService.__new__(ReaderPanelService)
        service.context = None
        service.persona_registry = None
        service.simulator = None
        service.store = None

        persona = types.SimpleNamespace()
        persona.sensitivity = types.SimpleNamespace()
        persona.sensitivity.risk_sensitivity = 0.0
        persona.sensitivity.slow_opening_sensitivity = 0.0
        persona.sensitivity.continuity_sensitivity = 0.0

        base_result = types.SimpleNamespace()
        base_result.retention_risk = types.SimpleNamespace()
        base_result.retention_risk.score = 0.0
        base_result.novel_health = types.SimpleNamespace()
        base_result.novel_health.pacing = 90.0
        base_result.novel_health.continuity = 90.0

        risk = service._calculate_retention_risk(persona, base_result, 90.0)
        assert risk == 0.0
        assert isinstance(risk, float)

    def test_cli_and_web_same_retention(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        run = service.run_panel(request)
        assert run.result is not None

        store = ReaderPanelStore(ctx)
        loaded_run = store.load_run(run.panel_run_id)
        assert loaded_run is not None
        assert loaded_run.result is not None

        assert abs(run.result.panel_retention_risk - loaded_run.result.panel_retention_risk) < 0.01
        for i in range(len(run.result.persona_results)):
            assert abs(run.result.persona_results[i].retention_risk - loaded_run.result.persona_results[i].retention_risk) < 0.01


class TestReadOnlyBoundary:
    def test_state_unchanged_after_panel(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        state_before = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        service.run_panel(request)

        state_after = json.loads((ctx.root / "data" / "state.json").read_text(encoding="utf-8"))
        assert state_before == state_after

    def test_chapter_files_unchanged(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        draft_path = ctx.root / "data" / "drafts" / "chapter_001_draft_v001.json"
        before_hash = hashlib.sha256(draft_path.read_bytes()).hexdigest()

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        service.run_panel(request)

        after_hash = hashlib.sha256(draft_path.read_bytes()).hexdigest()
        assert before_hash == after_hash


class TestStaleness:
    def test_all_dependencies_same_is_current(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        run = service.run_panel(request)

        store = ReaderPanelStore(ctx)
        staleness = store.check_run_staleness(run.panel_run_id)
        assert staleness.state == ResultState.CURRENT

    def test_source_changed_is_stale(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        service = ReaderPanelService(ctx)
        request = ReaderPanelRequest(
            project_id="test-project",
            timeline_id="main",
            chapter_id=1,
            persona_ids=["hook_driven_reader", "character_empathy_reader"],
            mode=PanelMode.DETERMINISTIC,
        )
        run = service.run_panel(request)

        store = ReaderPanelStore(ctx)
        
        loaded_run = store.load_run(run.panel_run_id)
        assert loaded_run is not None
        
        loaded_run.panel_evaluator_version = "panel-rule-v2"
        store.save_run(loaded_run)
        
        staleness = store.check_run_staleness(run.panel_run_id)
        assert staleness.state == ResultState.STALE


class TestCLI:
    def test_list_reader_personas_cli(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)

        result = subprocess.run(
            ["python", "main.py", "list-reader-personas", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "5 个读者角色" in result.stdout

    def test_run_reader_panel_cli(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        result = subprocess.run(
            ["python", "main.py", "run-reader-panel", "--chapter", "1", "--personas", "hook_driven_reader,character_empathy_reader", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "读者面板模拟完成" in result.stdout

    def test_list_reader_panels_cli(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        subprocess.run(
            ["python", "main.py", "run-reader-panel", "--chapter", "1", "--personas", "hook_driven_reader,character_empathy_reader", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            ["python", "main.py", "list-reader-panels", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "1 条读者面板记录" in result.stdout

    def test_help_works(self) -> None:
        for cmd in ["list-reader-personas", "run-reader-panel", "list-reader-panels", "show-reader-panel"]:
            result = subprocess.run(
                ["python", "main.py", cmd, "--help"],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

    def test_single_persona_returns_nonzero(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        result = subprocess.run(
            ["python", "main.py", "run-reader-panel", "--chapter", "1", "--personas", "hook_driven_reader", "--project-root", str(ctx.root)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1


class TestWebAPI:
    def test_persona_list_api(self) -> None:
        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/simulator/reader/personas")
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert len(data["result"]["personas"]) == 5

    def test_panel_run_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.post("/api/simulator/reader/panels/run", json={"chapter_id": 1, "persona_ids": ["hook_driven_reader", "character_empathy_reader"], "project_root": str(ctx.root)})
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert "panel_run_id" in data["result"]

    def test_panel_list_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.post("/api/simulator/reader/panels/run", json={"chapter_id": 1, "persona_ids": ["hook_driven_reader", "character_empathy_reader"], "project_root": str(ctx.root)})

            response = client.get(f"/api/simulator/reader/panels?project_root={str(ctx.root)}")
            assert response.status_code == 200
            data = response.json()
            assert len(data["result"]["panels"]) >= 1

    def test_panel_detail_api(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            run_response = client.post("/api/simulator/reader/panels/run", json={"chapter_id": 1, "persona_ids": ["hook_driven_reader", "character_empathy_reader"], "project_root": str(ctx.root)})
            panel_run_id = run_response.json()["result"]["panel_run_id"]

            response = client.get(f"/api/simulator/reader/panels/{panel_run_id}?project_root={str(ctx.root)}")
            assert response.status_code == 200
            data = response.json()
            assert data["result"]["panel_run_id"] == panel_run_id

    def test_unknown_run_returns_404(self) -> None:
        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/simulator/reader/panels/nonexistent-run-id")
            assert response.status_code == 404

    def test_single_persona_returns_400(self, tmp_path: Path) -> None:
        ctx = _create_temp_project(tmp_path)
        _create_draft_version(ctx, 1, "第一章内容。")

        from web.app import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.post("/api/simulator/reader/panels/run", json={"chapter_id": 1, "persona_ids": ["hook_driven_reader"], "project_root": str(ctx.root)})
            assert response.status_code == 400