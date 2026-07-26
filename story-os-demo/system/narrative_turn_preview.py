"""Read-only Narrative Turn Preview Service.

Phase 0D4-B: produces qualitative, deterministic preview projections
from a validated action + context snapshot.

STRICTLY READ-ONLY:
- Does NOT write NarrativeTurnResult
- Does NOT write to Result store
- Does NOT append 'previewed' transition
- Does NOT modify branch state
- Does NOT generate state delta
- Does NOT modify Canon
- Does NOT call Provider
- Same input → same preview fingerprint
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any

from core.contracts.narrative_turn import (
    ActionSource,
    NarrativeActionValidation,
    NarrativeActionOption,
    NarrativeTurnPlan,
    ValidationStatus,
)
from core.contracts.narrative_turn_preview import (
    NarrativeTurnPreview,
    compute_preview_fingerprint,
)
from system.narrative_turn_context import NarrativeTurnContextSnapshot, _stable_fingerprint


PREVIEW_REVISION = "narrative-turn-preview-v1"


def _generate_consequences(
    status: ValidationStatus,
    action: NarrativeActionOption | None,
    snapshot: NarrativeTurnContextSnapshot,
) -> tuple[str, ...]:
    """Generate qualitative likely consequences.

    IMPORTANT: These are qualitative projections, NOT facts.
    They are phrased conditionally (e.g., "可能会" / "may result in")
    and never assert that something has already happened.
    """
    if status == ValidationStatus.BLOCKED:
        return (
            "行动因确定性阻碍而无法执行，预期不会产生推进效果。",
            "需要先解决阻塞因素才能继续。",
        )

    if status == ValidationStatus.REQUIRES_CLARIFICATION:
        return (
            "行动信息不足，无法判断具体后果。",
            "补充行动细节后可以获得更清晰的预测。",
        )

    # Allowed or allowed_with_cost — generate based on action type
    consequences: list[str] = []

    if action is None:
        return ("行动可能产生预期效果，但存在不确定性。",)

    action_type = action.action_type.value

    if action_type == "advance":
        consequences.append("可能推进当前章节目标，带来剧情进展。")
        consequences.append("可能触发新的剧情节点或揭示信息。")
    elif action_type == "investigate":
        consequences.append("可能获得新的情报或线索。")
        consequences.append("调查结果可能与预期不同，存在意外发现的可能。")
    elif action_type == "retreat":
        consequences.append("可能降低当前风险水平，争取评估时间。")
        consequences.append("可能错失推进机会，导致时间成本。")
    elif action_type == "negotiate":
        consequences.append("可能达成一定程度的合作或妥协。")
        consequences.append("谈判结果受关系状态和对方立场影响，存在不确定性。")
    elif action_type == "sacrifice":
        consequences.append("可能以显著资源或关系代价换取关键突破。")
        consequences.append("牺牲的影响可能是长期且不可逆的。")
    else:
        consequences.append("行动后果存在多种可能性，具体取决于实际执行。")

    if status == ValidationStatus.ALLOWED_WITH_COST:
        consequences.append("已知存在需要承担的明确代价。")

    return tuple(consequences)


def _generate_limitations(
    status: ValidationStatus,
    snapshot: NarrativeTurnContextSnapshot,
) -> tuple[str, ...]:
    """Explicitly state what this preview cannot predict."""
    limitations = [
        "本预览为定性预测，不代表已经发生的事实。",
        "实际结果可能因执行细节和不可预见因素而不同。",
        "预览不包含精确数值、概率或定量指标。",
    ]

    if "CHAPTER_PLAN_MISSING" in snapshot.limitations:
        limitations.append("缺少当前章节规划，预测精度受限。")
    if "CANON_REVISION_MISSING" in snapshot.limitations:
        limitations.append("缺少 Canon 修订版信息，一致性校验不完整。")
    if "WORLD_DATA_SPARSE" in snapshot.limitations:
        limitations.append("世界设定数据较少，规则校验范围有限。")
    if "CHARACTER_DATA_SPARSE" in snapshot.limitations:
        limitations.append("角色数据较少，能力和关系判断受限。")

    if status == ValidationStatus.REQUIRES_CLARIFICATION:
        limitations.append("行动信息不足，无法做出确定性预测。")

    if status == ValidationStatus.BLOCKED:
        limitations.append("行动被阻塞，仅说明阻塞原因，不预测执行后果。")

    return tuple(sorted(set(limitations)))


def _generate_evidence_codes(
    status: ValidationStatus,
    validation: NarrativeActionValidation,
    snapshot: NarrativeTurnContextSnapshot,
) -> tuple[str, ...]:
    """Structured evidence codes backing the preview."""
    codes: set[str] = set()

    codes.add("PREVIEW_QUALITATIVE_ONLY")
    codes.add(f"VALIDATION_{status.value.upper()}")

    for ev in snapshot.evidence_codes:
        codes.add(ev)

    for reason in validation.blocking_reasons:
        codes.add(f"REASON_{reason}")

    return tuple(sorted(codes))


class NarrativeTurnPreviewService:
    """Read-only preview service.

    Pure computation. No writes. No Provider. No network.
    """

    REVISION = PREVIEW_REVISION

    @staticmethod
    def preview_recommended(
        *,
        plan: NarrativeTurnPlan,
        action: NarrativeActionOption,
        validation: NarrativeActionValidation,
        snapshot: NarrativeTurnContextSnapshot,
        clock_now: str,
    ) -> NarrativeTurnPreview:
        """Generate a preview for a recommended action."""
        return _build_preview(
            plan=plan,
            action=action,
            validation=validation,
            snapshot=snapshot,
            action_source="recommended",
            clock_now=clock_now,
        )

    @staticmethod
    def preview_custom(
        *,
        plan: NarrativeTurnPlan,
        validation: NarrativeActionValidation,
        snapshot: NarrativeTurnContextSnapshot,
        clock_now: str,
    ) -> NarrativeTurnPreview:
        """Generate a preview for a custom action."""
        return _build_preview(
            plan=plan,
            action=None,
            validation=validation,
            snapshot=snapshot,
            action_source="custom",
            clock_now=clock_now,
        )


def _build_preview(
    *,
    plan: NarrativeTurnPlan,
    action: NarrativeActionOption | None,
    validation: NarrativeActionValidation,
    snapshot: NarrativeTurnContextSnapshot,
    action_source: str,
    clock_now: str,
) -> NarrativeTurnPreview:
    """Build the immutable preview DTO."""
    status = validation.status

    # Expected costs: from validation, or from action if validation doesn't have them
    expected_costs = validation.cost_explanation
    if not expected_costs and action:
        expected_costs = action.expected_costs

    expected_risks = validation.risk_explanation
    if not expected_risks and action:
        expected_risks = action.expected_risks

    likely_consequences = _generate_consequences(status, action, snapshot)
    limitations = _generate_limitations(status, snapshot)
    evidence_codes = _generate_evidence_codes(status, validation, snapshot)

    selected_action_id = action.action_id if action else None
    custom_hash = validation.custom_action_text_hash

    preview_fp = compute_preview_fingerprint(
        turn_id=plan.turn_id,
        action_source=action_source,
        selected_action_id=selected_action_id,
        custom_action_text_hash=custom_hash,
        validation_status=status,
        expected_costs=expected_costs,
        expected_risks=expected_risks,
        likely_consequences=likely_consequences,
        evidence_codes=evidence_codes,
        limitations=limitations,
        context_fingerprint=snapshot.context_fingerprint,
    )

    # Deterministic preview_id
    id_input = {
        "preview_revision": PREVIEW_REVISION,
        "turn_id": plan.turn_id,
        "action_source": action_source,
        "selected_action_id": selected_action_id,
        "custom_action_text_hash": custom_hash,
        "context_fingerprint": snapshot.context_fingerprint,
        "preview_fingerprint": preview_fp,
    }
    preview_id = f"prev_{_stable_fingerprint(id_input)[:16]}"

    return NarrativeTurnPreview(
        schema_version=plan.schema_version,
        preview_id=preview_id,
        turn_id=plan.turn_id,
        scope=plan.scope,
        chapter_id=plan.chapter_id,
        action_source=action_source,
        selected_action_id=selected_action_id,
        custom_action_text_hash=custom_hash,
        validation_status=status,
        expected_costs=expected_costs,
        expected_risks=expected_risks,
        likely_consequences=likely_consequences,
        evidence_codes=evidence_codes,
        limitations=limitations,
        context_fingerprint=snapshot.context_fingerprint,
        preview_fingerprint=preview_fp,
        generated_at=clock_now,
    )
