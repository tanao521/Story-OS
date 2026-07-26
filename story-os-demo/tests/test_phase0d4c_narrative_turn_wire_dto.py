"""Phase 0D4-C focused tests: HTTP Wire DTO adapter.

Verifies that ``web.narrative_turn_wire`` converts Python domain contracts
(frozen dataclasses with tuple-of-pairs and enums) into JSON-serializable
Wire DTOs that contain only JSON primitives, objects, and arrays.

Covers:
- ContextWireDTO / PlanWireDTO / ValidationWireDTO / PreviewWireDTO schemas
- exactly 3 recommended actions
- custom_action_policy.max_length == 200
- enum → string conversion
- tuple-of-pairs → array of {key, level} objects
- no Python accessor / method name / Path / datetime exposed
- no absolute path leaks
- assert_json_safe rejects NaN / Infinity / Path / set / bytes / tuple
- error envelope shape
- custom action raw text never echoed (only SHA-256 hash)
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.contracts.narrative_turn import (
    ActionSource,
    ActionType,
    NarrativeActionOption,
    NarrativeBranch,
    NarrativeCustomActionPolicy,
    NarrativeScope,
    NarrativeTurnPlan,
    TimelineContext,
    ValidationStatus,
    SCHEMA_VERSION,
)
from core.contracts.narrative_turn_preview import NarrativeTurnPreview
from core.project_context import ProjectContext, get_project_context
from system.narrative_action_feasibility import (
    MAX_CUSTOM_ACTION_LENGTH,
    NarrativeActionFeasibility,
    normalize_custom_action,
)
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_turn_context import (
    NarrativeTurnContextBinder,
    NarrativeTurnContextSnapshot,
    PLANNER_REVISION,
)
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_preview import (
    NarrativeTurnPreviewService,
    PREVIEW_REVISION,
)
from web.narrative_turn_wire import (
    assert_json_safe,
    build_context_wire_dto,
    build_plan_wire_dto,
    build_preview_wire_dto,
    build_validation_wire_dto,
    error_envelope,
)


FIXED_CLOCK = "2025-01-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Seed helpers (mirrors test_phase0d4b_narrative_turn_planner.py)
# ---------------------------------------------------------------------------

def _seed_minimal_project(ctx: ProjectContext) -> None:
    data_dir = ctx.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    ctx.chapters_dir.mkdir(parents=True, exist_ok=True)
    ctx.narrative_state_dir.mkdir(parents=True, exist_ok=True)

    planning = {
        "schema_version": "1.0",
        "chapters": [
            {
                "chapter_id": "ch-001-test",
                "chapter_number": 1,
                "title": "第一章：启程",
                "goal": "主角离开家乡，踏上旅程",
                "conflicts": [{"id": "c1", "title": "迷雾森林的未知危险"}],
                "plot_threads": [
                    {"thread_id": "t1", "title": "失踪的旅人", "status": "active"},
                ],
            }
        ],
    }
    (data_dir / "story_planning.json").write_text(
        json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    world = {
        "schema_version": "1.0",
        "core_rules": [{"id": "r1", "rule": "魔法需要消耗精神力"}],
        "taboos_or_limits": ["使用禁忌魔法"],
        "locations": [{"id": "loc1", "name": "迷雾森林"}],
        "resources": {"金币": {"amount": 100, "unit": "枚"}},
    }
    (data_dir / "world_bible.json").write_text(
        json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chars = {
        "schema_version": "1.0",
        "main_characters": [
            {"id": "mc1", "name": "林远", "role": "protagonist", "capabilities": ["剑术"]},
        ],
    }
    (data_dir / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.chapters_dir / "chapter_001.md").write_text(
        "# 第一章：启程\n\n林远站在村口。", encoding="utf-8",
    )

    rolling = {
        "schema_version": "1.0",
        "current_chapter": 1,
        "remaining_chapters": 5,
        "window_size": 3,
    }
    ctx.rolling_window_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.rolling_window_path.write_text(
        json.dumps(rolling, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    deps = {"schema_version": "1.0", "blocking_dependencies": []}
    ctx.planning_dependencies_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.planning_dependencies_path.write_text(
        json.dumps(deps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.narrative_state_dir / "current.json").write_text(
        json.dumps({"chapter": 1, "time_of_day": "morning"}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def temp_project() -> ProjectContext:
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = get_project_context(tmpdir)
        _seed_minimal_project(ctx)
        yield ctx


@pytest.fixture
def branch_store(temp_project: ProjectContext) -> NarrativeBranchStore:
    return NarrativeBranchStore(temp_project)


@pytest.fixture
def timeline_ctx(temp_project: ProjectContext) -> TimelineContext:
    return TimelineContext(project_id=temp_project.root.name, timeline_id="tl-main")


@pytest.fixture
def open_branch(
    temp_project: ProjectContext,
    timeline_ctx: TimelineContext,
    branch_store: NarrativeBranchStore,
) -> NarrativeBranch:
    branch = branch_store.create_branch(timeline_ctx, "root", "Root Branch")
    revision = branch_store.get_registry_revision(timeline_ctx)
    branch_store.select_branch(timeline_ctx, "root", revision)
    return branch


@pytest.fixture
def scope(temp_project: ProjectContext, open_branch: NarrativeBranch) -> NarrativeScope:
    return NarrativeScope(
        project_id=temp_project.root.name,
        timeline_id="tl-main",
        branch_id=open_branch.branch_id,
    )


@pytest.fixture
def binder(temp_project: ProjectContext) -> NarrativeTurnContextBinder:
    return NarrativeTurnContextBinder(temp_project)


@pytest.fixture
def snapshot(binder: NarrativeTurnContextBinder, scope: NarrativeScope) -> NarrativeTurnContextSnapshot:
    return binder.bind(scope, chapter_id=1)


@pytest.fixture
def plan(snapshot: NarrativeTurnContextSnapshot) -> NarrativeTurnPlan:
    return NarrativeTurnPlanner.build_plan(snapshot, clock_now=FIXED_CLOCK)


@pytest.fixture
def recommended_action(plan: NarrativeTurnPlan) -> NarrativeActionOption:
    return plan.recommended_actions[0]


@pytest.fixture
def recommended_validation(
    snapshot: NarrativeTurnContextSnapshot,
    plan: NarrativeTurnPlan,
    recommended_action: NarrativeActionOption,
) -> Any:
    return NarrativeActionFeasibility.validate_recommended(
        snapshot, recommended_action, plan.turn_id, clock_now=FIXED_CLOCK,
    )


@pytest.fixture
def custom_validation(
    snapshot: NarrativeTurnContextSnapshot,
    plan: NarrativeTurnPlan,
) -> Any:
    normalized = normalize_custom_action("林远进入迷雾森林侦查")
    return NarrativeActionFeasibility.validate_custom(
        snapshot, normalized, plan.turn_id, clock_now=FIXED_CLOCK,
    )


@pytest.fixture
def recommended_preview(
    snapshot: NarrativeTurnContextSnapshot,
    plan: NarrativeTurnPlan,
    recommended_action: NarrativeActionOption,
    recommended_validation: Any,
) -> NarrativeTurnPreview:
    return NarrativeTurnPreviewService.preview_recommended(
        plan=plan,
        action=recommended_action,
        validation=recommended_validation,
        snapshot=snapshot,
        clock_now=FIXED_CLOCK,
    )


@pytest.fixture
def custom_preview(
    snapshot: NarrativeTurnContextSnapshot,
    plan: NarrativeTurnPlan,
    custom_validation: Any,
) -> NarrativeTurnPreview:
    return NarrativeTurnPreviewService.preview_custom(
        plan=plan,
        validation=custom_validation,
        snapshot=snapshot,
        clock_now=FIXED_CLOCK,
    )


# ===========================================================================
# Section 1: ContextWireDTO
# ===========================================================================

class TestContextWireDTO:
    def test_schema_version_present(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert dto["schema_version"] == snapshot.schema_version

    def test_scope_block(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert dto["scope"] == {
            "project_id": snapshot.scope.project_id,
            "timeline_id": snapshot.scope.timeline_id,
            "branch_id": snapshot.scope.branch_id,
        }

    def test_chapter_and_source(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert dto["chapter_id"] == snapshot.chapter_id
        assert dto["source_version_id"] == snapshot.source_version_id

    def test_fingerprints_and_revisions(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert dto["context_fingerprint"] == snapshot.context_fingerprint
        assert dto["canon_revision"] == snapshot.canon_revision
        assert dto["planner_revision"] == snapshot.planner_revision
        assert dto["planner_revision"] == PLANNER_REVISION

    def test_branch_block_dimensions(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        branch = dto["branch"]
        assert set(branch.keys()) == {"lifecycle", "activity", "narrative_state_data"}
        assert branch["lifecycle"] in ("open", "archived")
        assert branch["activity"] in ("active", "inactive")
        assert branch["narrative_state_data"] in (
            "available", "unavailable", "scope_mismatch", "invalid",
        )

    def test_branch_block_matches_snapshot(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        branch = dto["branch"]
        assert branch["lifecycle"] == ("open" if snapshot.branch_open else "archived")
        assert branch["activity"] == ("active" if snapshot.branch_is_active else "inactive")

    def test_situation_block_structure(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        situation = dto["situation"]
        expected_keys = {
            "chapter_goal", "active_conflicts", "characters", "locations",
            "resources", "world_rules", "open_threads", "time_window", "dependencies",
        }
        assert set(situation.keys()) == expected_keys

    def test_situation_block_value_types(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        situation = dto["situation"]
        assert situation["chapter_goal"] is None or isinstance(situation["chapter_goal"], str)
        assert isinstance(situation["active_conflicts"], list)
        assert isinstance(situation["characters"], list)
        assert isinstance(situation["locations"], list)
        assert isinstance(situation["resources"], list)
        assert isinstance(situation["world_rules"], list)
        assert isinstance(situation["open_threads"], list)
        assert situation["time_window"] is None or isinstance(situation["time_window"], str)
        assert isinstance(situation["dependencies"], list)

    def test_evidence_codes_and_limitations_are_arrays(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert isinstance(dto["evidence_codes"], list)
        assert isinstance(dto["limitations"], list)
        for code in dto["evidence_codes"]:
            assert isinstance(code, str)
        for lim in dto["limitations"]:
            assert isinstance(lim, str)

    def test_json_serializable(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        text = json.dumps(dto, ensure_ascii=False)
        assert "Traceback" not in text
        assert "Path(" not in text
        assert "datetime" not in text

    def test_assert_json_safe_passes(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        assert_json_safe(dto)

    def test_no_python_accessor_exposed(self, snapshot: NarrativeTurnContextSnapshot) -> None:
        dto = build_context_wire_dto(snapshot)
        text = json.dumps(dto, ensure_ascii=False)
        # Method names must never appear in the wire DTO.
        assert "planning_data_dict" not in text
        assert "chapter_plan_dict" not in text
        assert "world_data_dict" not in text
        assert "character_data_dict" not in text
        assert "narrative_state_dict" not in text
        assert "rolling_window_dict" not in text
        assert "dependencies_dict" not in text
        # The DTO must not contain callable values.
        for value in dto.values():
            assert not callable(value)

    def test_no_absolute_path_leak(self, snapshot: NarrativeTurnContextSnapshot, temp_project: ProjectContext) -> None:
        dto = build_context_wire_dto(snapshot)
        text = json.dumps(dto, ensure_ascii=False)
        # The temp project root must never appear in the wire DTO.
        assert str(temp_project.root) not in text
        assert str(temp_project.root.resolve()) not in text
        # Windows-style drive letters should not appear in scope.
        assert ":\\" not in text and ":/" not in text


# ===========================================================================
# Section 2: PlanWireDTO
# ===========================================================================

class TestPlanWireDTO:
    def test_top_level_fields(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        assert dto["schema_version"] == plan.schema_version
        assert dto["turn_id"] == plan.turn_id
        assert dto["chapter_id"] == plan.chapter_id
        assert dto["source_version_id"] == plan.source_version_id
        assert dto["context_fingerprint"] == plan.context_fingerprint
        assert dto["planner_revision"] == plan.planning_revision
        assert dto["canon_revision"] == plan.canon_revision
        assert dto["scope"] == {
            "project_id": plan.scope.project_id,
            "timeline_id": plan.scope.timeline_id,
            "branch_id": plan.scope.branch_id,
        }

    def test_recommended_actions_count_is_exactly_3(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        assert len(dto["recommended_actions"]) == 3
        assert len(plan.recommended_actions) == 3

    def test_recommended_action_preserves_deterministic_order(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        orders = [a["deterministic_order"] for a in dto["recommended_actions"]]
        assert orders == [1, 2, 3]

    def test_recommended_action_does_not_rerorder(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        original_ids = [a.action_id for a in plan.recommended_actions]
        dto_ids = [a["action_id"] for a in dto["recommended_actions"]]
        assert dto_ids == original_ids

    def test_recommended_action_fields(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        action_dto = dto["recommended_actions"][0]
        expected_keys = {
            "action_id", "action_type", "display_text", "intent",
            "expected_costs", "expected_risks", "required_conditions",
            "unavailable_reasons", "provenance", "deterministic_order",
        }
        assert set(action_dto.keys()) == expected_keys

    def test_action_type_is_string_not_enum(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        for action in dto["recommended_actions"]:
            assert isinstance(action["action_type"], str)
            assert not isinstance(action["action_type"], type)

    def test_expected_costs_is_array_of_objects(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        for action in dto["recommended_actions"]:
            assert isinstance(action["expected_costs"], list)
            for cost in action["expected_costs"]:
                assert set(cost.keys()) == {"key", "level"}
                assert isinstance(cost["key"], str)
                assert isinstance(cost["level"], str)
            assert isinstance(action["expected_risks"], list)
            for risk in action["expected_risks"]:
                assert set(risk.keys()) == {"key", "level"}

    def test_required_conditions_and_unavailable_reasons_are_string_arrays(
        self, plan: NarrativeTurnPlan,
    ) -> None:
        dto = build_plan_wire_dto(plan)
        for action in dto["recommended_actions"]:
            assert isinstance(action["required_conditions"], list)
            assert isinstance(action["unavailable_reasons"], list)
            for cond in action["required_conditions"]:
                assert isinstance(cond, str)
            for reason in action["unavailable_reasons"]:
                assert isinstance(reason, str)

    def test_custom_action_policy_max_length_is_200(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        policy = dto["custom_action_policy"]
        assert policy["max_length"] == MAX_CUSTOM_ACTION_LENGTH
        assert policy["max_length"] == 200

    def test_custom_action_policy_arrays(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        policy = dto["custom_action_policy"]
        assert isinstance(policy["forbidden_patterns"], list)
        assert isinstance(policy["feasibility_pipeline"], list)
        for item in policy["forbidden_patterns"]:
            assert isinstance(item, str)
        for item in policy["feasibility_pipeline"]:
            assert isinstance(item, str)

    def test_json_serializable(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        text = json.dumps(dto, ensure_ascii=False)
        assert "Traceback" not in text
        assert "Path(" not in text

    def test_assert_json_safe_passes(self, plan: NarrativeTurnPlan) -> None:
        dto = build_plan_wire_dto(plan)
        assert_json_safe(dto)


# ===========================================================================
# Section 3: ValidationWireDTO
# ===========================================================================

class TestValidationWireDTO:
    def test_recommended_validation_top_level_fields(self, recommended_validation: Any, plan: NarrativeTurnPlan) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert dto["schema_version"] == recommended_validation.schema_version
        assert dto["validation_id"] == recommended_validation.validation_id
        assert dto["turn_id"] == recommended_validation.turn_id
        assert dto["chapter_id"] == recommended_validation.chapter_id
        assert dto["context_fingerprint"] == recommended_validation.context_fingerprint
        assert dto["action_source"] == "recommended"
        assert dto["selected_action_id"] == recommended_validation.selected_action_id
        assert dto["custom_action_text_hash"] is None

    def test_custom_validation_top_level_fields(self, custom_validation: Any) -> None:
        dto = build_validation_wire_dto(custom_validation)
        assert dto["action_source"] == "custom"
        assert dto["selected_action_id"] is None
        assert dto["custom_action_text_hash"] is not None
        assert len(dto["custom_action_text_hash"]) == 64

    def test_status_is_string_not_enum(self, recommended_validation: Any) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert isinstance(dto["status"], str)
        assert dto["status"] in (
            "allowed", "allowed_with_cost", "requires_clarification", "blocked",
        )

    def test_blocking_reasons_is_string_array(self, recommended_validation: Any) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert isinstance(dto["blocking_reasons"], list)
        for reason in dto["blocking_reasons"]:
            assert isinstance(reason, str)

    def test_cost_and_risk_explanations_are_arrays_of_objects(self, recommended_validation: Any) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert isinstance(dto["cost_explanation"], list)
        assert isinstance(dto["risk_explanation"], list)
        for item in dto["cost_explanation"] + dto["risk_explanation"]:
            assert set(item.keys()) == {"key", "level"}

    def test_checked_at_is_iso_string(self, recommended_validation: Any) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert isinstance(dto["checked_at"], str)
        assert dto["checked_at"] == recommended_validation.checked_at

    def test_assert_json_safe_passes(self, recommended_validation: Any) -> None:
        dto = build_validation_wire_dto(recommended_validation)
        assert_json_safe(dto)

    def test_raw_custom_text_not_in_dto(
        self, custom_validation: Any,
    ) -> None:
        dto = build_validation_wire_dto(custom_validation)
        text = json.dumps(dto, ensure_ascii=False)
        # Raw custom text must never appear in the wire DTO.
        assert "林远进入迷雾森林侦查" not in text
        # Only the SHA-256 hash is exposed.
        assert dto["custom_action_text_hash"]
        assert all(c in "0123456789abcdef" for c in dto["custom_action_text_hash"])


# ===========================================================================
# Section 4: PreviewWireDTO
# ===========================================================================

class TestPreviewWireDTO:
    def test_recommended_preview_top_level_fields(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert dto["schema_version"] == recommended_preview.schema_version
        assert dto["preview_id"] == recommended_preview.preview_id
        assert dto["turn_id"] == recommended_preview.turn_id
        assert dto["chapter_id"] == recommended_preview.chapter_id
        assert dto["context_fingerprint"] == recommended_preview.context_fingerprint
        assert dto["preview_fingerprint"] == recommended_preview.preview_fingerprint
        assert dto["action_source"] == "recommended"
        assert dto["selected_action_id"] == recommended_preview.selected_action_id
        assert dto["custom_action_text_hash"] is None

    def test_custom_preview_top_level_fields(self, custom_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(custom_preview)
        assert dto["action_source"] == "custom"
        assert dto["selected_action_id"] is None
        assert dto["custom_action_text_hash"] is not None

    def test_validation_status_is_string(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert isinstance(dto["validation_status"], str)
        assert dto["validation_status"] in (
            "allowed", "allowed_with_cost", "requires_clarification", "blocked",
        )

    def test_expected_costs_and_risks_are_arrays_of_objects(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert isinstance(dto["expected_costs"], list)
        assert isinstance(dto["expected_risks"], list)
        for item in dto["expected_costs"] + dto["expected_risks"]:
            assert set(item.keys()) == {"key", "level"}

    def test_likely_consequences_is_string_array(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert isinstance(dto["likely_consequences"], list)
        for c in dto["likely_consequences"]:
            assert isinstance(c, str)

    def test_evidence_codes_and_limitations_are_string_arrays(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert isinstance(dto["evidence_codes"], list)
        assert isinstance(dto["limitations"], list)
        for code in dto["evidence_codes"]:
            assert isinstance(code, str)
        for lim in dto["limitations"]:
            assert isinstance(lim, str)

    def test_generated_at_is_iso_string(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert isinstance(dto["generated_at"], str)

    def test_raw_custom_text_not_in_preview_dto(self, custom_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(custom_preview)
        text = json.dumps(dto, ensure_ascii=False)
        assert "林远进入迷雾森林侦查" not in text
        assert all(c in "0123456789abcdef" for c in dto["custom_action_text_hash"])

    def test_assert_json_safe_passes(self, recommended_preview: NarrativeTurnPreview) -> None:
        dto = build_preview_wire_dto(recommended_preview)
        assert_json_safe(dto)


# ===========================================================================
# Section 5: assert_json_safe security boundary
# ===========================================================================

class TestAssertJsonSafe:
    def test_passes_for_primitives(self) -> None:
        assert_json_safe(None)
        assert_json_safe(True)
        assert_json_safe(False)
        assert_json_safe(0)
        assert_json_safe(1)
        assert_json_safe(-1)
        assert_json_safe("hello")

    def test_passes_for_finite_floats(self) -> None:
        assert_json_safe(1.0)
        assert_json_safe(-1.5)
        assert_json_safe(0.0)

    def test_rejects_nan(self) -> None:
        with pytest.raises(TypeError, match="NaN"):
            assert_json_safe(float("nan"))

    def test_rejects_infinity(self) -> None:
        with pytest.raises(TypeError, match="Infinity"):
            assert_json_safe(float("inf"))
        with pytest.raises(TypeError, match="Infinity"):
            assert_json_safe(float("-inf"))

    def test_rejects_tuple(self) -> None:
        with pytest.raises(TypeError, match="tuple"):
            assert_json_safe((1, 2, 3))

    def test_rejects_set(self) -> None:
        with pytest.raises(TypeError, match="set"):
            assert_json_safe({1, 2, 3})

    def test_rejects_bytes(self) -> None:
        with pytest.raises(TypeError, match="bytes"):
            assert_json_safe(b"raw")

    def test_rejects_path(self) -> None:
        with pytest.raises(TypeError, match="Path|WindowsPath|PosixPath"):
            assert_json_safe(Path("/tmp/x"))

    def test_rejects_custom_object(self) -> None:
        class Custom:
            pass
        with pytest.raises(TypeError, match="Custom"):
            assert_json_safe(Custom())

    def test_passes_for_nested_list_and_dict(self) -> None:
        assert_json_safe([1, "two", [3, 4], {"k": "v"}])
        assert_json_safe({"a": [1, 2], "b": {"c": "d"}})

    def test_rejects_nested_unsafe_value(self) -> None:
        with pytest.raises(TypeError):
            assert_json_safe({"a": [1, (2, 3)]})

    def test_rejects_non_string_dict_key(self) -> None:
        with pytest.raises(TypeError, match="non-string key"):
            assert_json_safe({1: "one"})


# ===========================================================================
# Section 6: error_envelope
# ===========================================================================

class TestErrorEnvelope:
    def test_envelope_shape(self) -> None:
        env = error_envelope("CONTEXT_STALE", "上下文已过期，请重新规划。", request_id=None)
        assert set(env.keys()) == {"error"}
        assert set(env["error"].keys()) == {"code", "message", "request_id"}
        assert env["error"]["code"] == "CONTEXT_STALE"
        assert env["error"]["message"] == "上下文已过期，请重新规划。"
        assert env["error"]["request_id"] is None

    def test_envelope_with_request_id(self) -> None:
        env = error_envelope("INTERNAL_ERROR", "x", request_id="req-123")
        assert env["error"]["request_id"] == "req-123"

    def test_envelope_json_serializable(self) -> None:
        env = error_envelope("CONTEXT_STALE", "上下文已过期。", None)
        text = json.dumps(env, ensure_ascii=False)
        assert "Traceback" not in text

    def test_envelope_assert_json_safe(self) -> None:
        env = error_envelope("CONTEXT_STALE", "上下文已过期。", None)
        assert_json_safe(env)
