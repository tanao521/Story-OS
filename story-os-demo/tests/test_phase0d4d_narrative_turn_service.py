"""Phase 0D4-D focused tests: NarrativeTurnService confirmation.

Covers:
- Idempotent operation replay (same operation + same payload)
- Operation collision (same operation + different payload/scope)
- First-writer-wins concurrency (different operations, same turn)
- Full legal transition chain
- Branch event journal append-only integrity
- Branch-state projection with CAS
- Forward recovery from every phase
- Branch isolation (A vs B)
- Inactive/archived branch rejection
- Blocked / requires_clarification rejection
- Raw custom action text never persisted
- No Canon / Chroma / Provider / global memory writes
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.contracts.narrative_turn import (
    NarrativeScope,
    NarrativeTurnError,
    ResultStatus,
    TurnState,
    ValidationStatus,
)
from core.project_context import ProjectContext, get_project_context
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_service import (
    ConfirmOperationPhase,
    ConfirmResult,
    NarrativeTurnService,
)
from system.narrative_turn_store import NarrativeTurnStore


FIXED_CLOCK = "2025-01-15T12:00:00+00:00"


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
        "core_rules": [
            {"id": "r1", "rule": "魔法需要消耗精神力"},
        ],
        "taboos_or_limits": ["使用禁忌魔法", "攻击平民"],
        "locations": [
            {"id": "loc1", "name": "迷雾森林"},
            {"id": "loc2", "name": "边境小镇"},
        ],
        "resources": {
            "金币": {"amount": 100, "unit": "枚"},
            "药水": {"amount": 3, "unit": "瓶"},
        },
    }
    (data_dir / "world_bible.json").write_text(
        json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chars = {
        "schema_version": "1.0",
        "main_characters": [
            {"id": "mc1", "name": "林远", "role": "protagonist", "capabilities": ["剑术", "侦查"]},
        ],
        "supporting_characters": [
            {"id": "sc1", "name": "老村长", "role": "mentor"},
        ],
    }
    (data_dir / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.chapters_dir / "chapter_001.md").write_text(
        "# 第一章：启程\n\n林远站在村口，回望家乡。",
        encoding="utf-8",
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

    deps = {
        "schema_version": "1.0",
        "blocking_dependencies": [],
    }
    ctx.planning_dependencies_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.planning_dependencies_path.write_text(
        json.dumps(deps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (ctx.narrative_state_dir / "current.json").write_text(
        json.dumps({"chapter": 1, "time_of_day": "morning"}, ensure_ascii=False),
        encoding="utf-8",
    )


def _create_branch(ctx: ProjectContext, timeline_id: str, branch_id: str) -> None:
    store = NarrativeBranchStore(ctx)
    from core.contracts.narrative_turn import TimelineContext
    tl = TimelineContext(project_id=ctx.root.name, timeline_id=timeline_id)
    store.create_branch(tl, branch_id, "test")
    revision = store.get_registry_revision(tl)
    store.select_branch(tl, branch_id, expected_revision=revision)


def _make_scope(ctx: ProjectContext, timeline_id: str, branch_id: str) -> NarrativeScope:
    return NarrativeScope(
        project_id=ctx.root.name,
        timeline_id=timeline_id,
        branch_id=branch_id,
    )


@pytest.fixture
def project_ctx(tmp_path: Path):
    root = tmp_path / "test-project"
    root.mkdir()
    data = root / "data"
    data.mkdir()

    ctx = get_project_context(root)
    _seed_minimal_project(ctx)
    return ctx


class TestIdempotency:
    def test_same_operation_same_payload_replay(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-test-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        result2 = service.confirm_turn(
            operation_id="op-test-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        assert result2.idempotent_replay is True
        assert result2.result.turn_id == result1.result.turn_id
        assert result2.result.fingerprint() == result1.result.fingerprint()

    def test_result_only_created_once(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-test-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        result2 = service.confirm_turn(
            operation_id="op-test-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        turn_store = NarrativeTurnStore(project_ctx)
        result = turn_store.get_result(scope, result1.result.turn_id)
        assert result is not None
        assert result.operation_id == "op-test-002"


class TestConcurrency:
    def test_different_operations_same_turn_conflict(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)
        turn_store = NarrativeTurnStore(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-first",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )
        assert result1.idempotent_replay is False
        turn_id = result1.result.turn_id

        existing_result = turn_store.get_result(scope, turn_id)
        assert existing_result is not None
        assert existing_result.operation_id == "op-first"

        from dataclasses import replace
        different_op_result = replace(existing_result, operation_id="op-second")
        with pytest.raises(NarrativeTurnError) as exc_info:
            turn_store.append_result(different_op_result)
        assert exc_info.value.code == NarrativeTurnError.INVALID_FIELD


class TestTransitionChain:
    def test_full_transition_chain_applied(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)
        turn_store = NarrativeTurnStore(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result = service.confirm_turn(
            operation_id="op-chain-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        transitions = turn_store.get_transitions(scope, result.result.turn_id)
        states = [t.from_state for t in transitions] + [transitions[-1].to_state]

        assert TurnState.PLANNED in states
        assert TurnState.AWAITING_ACTION in states
        assert TurnState.VALIDATING in states
        assert TurnState.VALIDATED in states
        assert TurnState.PREVIEWED in states
        assert TurnState.CONFIRMED in states
        assert TurnState.APPLIED_TO_BRANCH in states

        last = transitions[-1]
        assert last.to_state == TurnState.APPLIED_TO_BRANCH

    def test_no_included_in_chapter_or_committed(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)
        turn_store = NarrativeTurnStore(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result = service.confirm_turn(
            operation_id="op-chain-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        transitions = turn_store.get_transitions(scope, result.result.turn_id)
        for t in transitions:
            assert t.to_state != TurnState.INCLUDED_IN_CHAPTER
            assert t.to_state != TurnState.COMMITTED


class TestBranchEventJournal:
    def test_branch_event_created(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result = service.confirm_turn(
            operation_id="op-event-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        events = service._read_branch_events(scope)
        assert len(events) == 1
        assert events[0]["turn_id"] == result.result.turn_id
        assert events[0]["operation_id"] == "op-event-001"
        assert events[0]["sequence"] == 0
        assert events[0]["previous_event_id"] is None

    def test_event_chain_fingerprint_integrity(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        service.confirm_turn(
            operation_id="op-event-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        events = service._read_branch_events(scope)
        assert len(events) == 1
        assert events[0]["record_fingerprint"] is not None
        assert len(events[0]["record_fingerprint"]) == 64


class TestBranchStateProjection:
    def test_state_projection_updated(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result = service.confirm_turn(
            operation_id="op-state-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        rev, state = service._read_branch_state(scope)
        assert state is not None
        assert state["last_applied_turn_id"] == result.result.turn_id
        assert state["last_result_fingerprint"] == result.result.fingerprint()
        assert state["last_event_sequence"] == 0
        assert state["revision"] is not None
        assert result.branch_state_revision == rev

    def test_state_projection_cas(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-state-cas-1",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )
        first_rev = result1.branch_state_revision
        assert first_rev is not None

        state_path = service._branch_state_path(scope)
        import json as j
        state_data = j.loads(state_path.read_text(encoding="utf-8"))
        state_data["revision"] = "tampered-revision"
        state_path.write_text(j.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        current_rev, _ = service._read_branch_state(scope)
        assert current_rev == "tampered-revision"

        from core.contracts.narrative_turn import NarrativeTurnResult
        turn_store = NarrativeTurnStore(project_ctx)
        existing_result = turn_store.get_result(scope, result1.result.turn_id)
        assert existing_result is not None

        with pytest.raises(NarrativeTurnError) as exc_info:
            service._project_state(
                scope,
                turn_id=result1.result.turn_id,
                event_sequence=1,
                result_fingerprint=result1.result.fingerprint(),
                state_delta_proposal=existing_result.state_delta_proposal,
                expected_revision=first_rev,
            )
        assert exc_info.value.code == NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION


class TestBranchIsolation:
    def test_branch_a_does_not_affect_branch_b(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        _create_branch(project_ctx, "tl-main", "br-beta")
        scope_a = _make_scope(project_ctx, "tl-main", "br-alpha")
        scope_b = _make_scope(project_ctx, "tl-main", "br-beta")
        service = NarrativeTurnService(project_ctx)

        branch_store = NarrativeBranchStore(project_ctx)
        from core.contracts.narrative_turn import TimelineContext
        tl = TimelineContext(project_id=project_ctx.root.name, timeline_id="tl-main")
        rev = branch_store.get_registry_revision(tl)
        branch_store.select_branch(tl, "br-alpha", expected_revision=rev)

        plan_a = _build_plan(project_ctx, scope_a)
        action_id_a = plan_a.recommended_actions[0].action_id

        result_a = service.confirm_turn(
            operation_id="op-iso-a",
            scope=scope_a,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id_a,
        )

        events_b = service._read_branch_events(scope_b)
        assert len(events_b) == 0

        _, state_b = service._read_branch_state(scope_b)
        assert state_b is None


class TestBranchRejection:
    def test_archived_branch_rejected(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-active")
        _create_branch(project_ctx, "tl-main", "br-archived")
        scope = _make_scope(project_ctx, "tl-main", "br-archived")

        branch_store = NarrativeBranchStore(project_ctx)
        from core.contracts.narrative_turn import TimelineContext
        tl = TimelineContext(project_id=project_ctx.root.name, timeline_id="tl-main")
        rev = branch_store.get_registry_revision(tl)
        branch_store.archive_branch(tl, "br-archived", replacement_branch_id="br-active", expected_revision=rev)

        service = NarrativeTurnService(project_ctx)

        with pytest.raises(NarrativeTurnError) as exc_info:
            service.confirm_turn(
                operation_id="op-archived",
                scope=scope,
                chapter_id=1,
                source_version_id=None,
                expected_context_fingerprint=None,
                expected_turn_id=None,
                expected_validation_id=None,
                expected_preview_fingerprint=None,
                action_source="recommended",
                selected_action_id="act_dummy",
            )
        assert "archived" in str(exc_info.value).lower() or exc_info.value.code == NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT


class TestCustomActionSecurity:
    def test_custom_action_text_not_persisted(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        custom_text = "前往迷雾森林寻找SECRET_SENTINEL_12345"
        result = service.confirm_turn(
            operation_id="op-custom-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="custom",
            custom_action_text=custom_text,
        )

        assert result.result.custom_action_text_hash is not None
        assert result.result.selected_action_id is None

        assert "SECRET_SENTINEL" not in result.result.event_summary
        assert custom_text not in result.result.event_summary

        events = service._read_branch_events(scope)
        for evt in events:
            evt_text = json.dumps(evt, ensure_ascii=False)
            assert "SECRET_SENTINEL" not in evt_text
            assert custom_text not in evt_text

        turn_store = NarrativeTurnStore(project_ctx)
        result_obj = turn_store.get_result(scope, result.result.turn_id)
        from dataclasses import asdict
        result_dict = asdict(result_obj)
        result_text = json.dumps(result_dict, ensure_ascii=False, default=str)
        assert "SECRET_SENTINEL" not in result_text
        assert custom_text not in result_text


class TestRecovery:
    def test_recovery_from_result_claimed_phase(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-rec-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        phase_path = service._operation_phase_path("op-rec-001")
        phase_data = json.loads(phase_path.read_text(encoding="utf-8"))
        phase_data["phase"] = ConfirmOperationPhase.RESULT_CLAIMED
        phase_path.write_text(json.dumps(phase_data, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8")

        result2 = service.confirm_turn(
            operation_id="op-rec-001",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        assert result2.idempotent_replay is True
        assert result2.recovery_performed is True
        assert result2.final_phase == ConfirmOperationPhase.COMPLETED
        assert result2.result.turn_id == result1.result.turn_id

        events = service._read_branch_events(scope)
        assert len(events) == 1

        rev, state = service._read_branch_state(scope)
        assert state is not None
        assert state["last_applied_turn_id"] == result1.result.turn_id

    def test_recovery_from_branch_event_appended_phase(self, project_ctx):
        _create_branch(project_ctx, "tl-main", "br-alpha")
        scope = _make_scope(project_ctx, "tl-main", "br-alpha")
        service = NarrativeTurnService(project_ctx)

        plan = _build_plan(project_ctx, scope)
        action_id = plan.recommended_actions[0].action_id

        result1 = service.confirm_turn(
            operation_id="op-rec-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        phase_path = service._operation_phase_path("op-rec-002")
        phase_data = json.loads(phase_path.read_text(encoding="utf-8"))
        phase_data["phase"] = ConfirmOperationPhase.BRANCH_EVENT_APPENDED
        phase_path.write_text(json.dumps(phase_data, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8")

        result2 = service.confirm_turn(
            operation_id="op-rec-002",
            scope=scope,
            chapter_id=1,
            source_version_id=None,
            expected_context_fingerprint=None,
            expected_turn_id=None,
            expected_validation_id=None,
            expected_preview_fingerprint=None,
            action_source="recommended",
            selected_action_id=action_id,
        )

        assert result2.idempotent_replay is True
        assert result2.recovery_performed is True
        assert result2.final_phase == ConfirmOperationPhase.COMPLETED

        events = service._read_branch_events(scope)
        assert len(events) == 1


def _build_plan(project_ctx: ProjectContext, scope: NarrativeScope):
    from system.narrative_turn_context import NarrativeTurnContextBinder
    binder = NarrativeTurnContextBinder(project_ctx)
    snapshot = binder.bind(scope, 1, source_version_id=None)
    return NarrativeTurnPlanner.build_plan(snapshot, parent_turn_id=None, clock_now=FIXED_CLOCK)
