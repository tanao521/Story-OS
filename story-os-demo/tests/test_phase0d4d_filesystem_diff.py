"""Exact filesystem-diff acceptance for Phase 0D4-D-RC1."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.contracts.narrative_turn import NarrativeTurnError
from core.project_context import get_project_context
from system.narrative_turn_service import NarrativeTurnService
from tests.test_phase0d4d_narrative_turn_service import (
    _build_plan,
    _create_branch,
    _make_scope,
    _seed_minimal_project,
)


def _manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _request(ctx, timeline: str, branch: str, operation: str, *, custom: str | None = None):
    scope = _make_scope(ctx, timeline, branch)
    plan = _build_plan(ctx, scope)
    request = {
        "operation_id": operation,
        "scope": scope,
        "chapter_id": 1,
        "source_version_id": None,
        "expected_context_fingerprint": None,
        "expected_turn_id": None,
        "expected_validation_id": None,
        "expected_preview_fingerprint": None,
        "action_source": "custom" if custom else "recommended",
        "selected_action_id": None if custom else plan.recommended_actions[0].action_id,
        "custom_action_text": custom,
    }
    return request


def test_expected_only_filesystem_diff(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    ctx = get_project_context(root)
    _seed_minimal_project(ctx)
    for timeline, branch in (
        ("tl-recommended", "br-root"),
        ("tl-custom", "br-root"),
        ("tl-recovery", "br-root"),
    ):
        _create_branch(ctx, timeline, branch)
        state_path = ctx.narrative_state_dir / timeline / branch / "current.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "project_id": ctx.root.name,
                    "timeline_id": timeline,
                    "branch_id": branch,
                    "chapter": 1,
                }
            ),
            encoding="utf-8",
        )

    before = _manifest(root)
    recommended = _request(
        ctx, "tl-recommended", "br-root", "op-fs-recommended"
    )
    custom = _request(
        ctx,
        "tl-custom",
        "br-root",
        "op-fs-custom",
        custom="investigate the forest",
    )
    recovery = _request(ctx, "tl-recovery", "br-root", "op-fs-recovery")

    service = NarrativeTurnService(ctx)
    service.confirm_turn(**recommended)
    replay = NarrativeTurnService(ctx).confirm_turn(**recommended)
    assert replay.idempotent_replay is True

    competing = dict(recommended)
    competing["operation_id"] = "op-fs-competing"
    with pytest.raises(NarrativeTurnError) as exc:
        NarrativeTurnService(ctx).confirm_turn(**competing)
    assert exc.value.code in {
        NarrativeTurnError.TURN_ALREADY_CONFIRMED,
        NarrativeTurnError.ACTION_INVALID,
        NarrativeTurnError.CONTEXT_STALE,
    }

    NarrativeTurnService(ctx).confirm_turn(**custom)

    def inject(point: str) -> None:
        if point == "after_branch_event_append":
            raise RuntimeError(point)

    with pytest.raises(RuntimeError):
        NarrativeTurnService(ctx, fault_injector=inject).confirm_turn(**recovery)
    NarrativeTurnService(ctx).confirm_turn(**recovery)

    after = _manifest(root)
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    allowed_prefixes = (
        "data/narrative_turn/plans/",
        "data/narrative_turn/validations/",
        "data/narrative_turn/results/",
        "data/narrative_turn/transitions/",
        "data/narrative_turn/operations/",
        "data/narrative_turn/events/",
        "data/narrative_memory/state/tl-recommended/br-root/current.",
        "data/narrative_memory/state/tl-custom/br-root/current.",
        "data/narrative_memory/state/tl-recovery/br-root/current.",
    )
    unexpected = sorted(
        path for path in changed if not path.startswith(allowed_prefixes)
    )
    assert unexpected == []

    protected_prefixes = (
        "data/canon",
        "data/chroma",
        "data/vector",
        "data/branches/",
        "data/narrative_memory/events/",
        "data/story_planning.json",
        "data/versions/",
    )
    protected_changes = sorted(
        path for path in changed if path.startswith(protected_prefixes)
    )
    assert protected_changes == []
