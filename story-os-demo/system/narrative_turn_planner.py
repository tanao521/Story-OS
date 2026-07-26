"""Deterministic Narrative Turn Planner.

Phase 0D4-B: pure-computation planner that produces exactly 3
recommended actions from structured context evidence.

No file writes, no store writes, no Provider calls, no network,
no randomness. Same input always produces the same Plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from core.contracts.narrative_turn import (
    ActionType,
    NarrativeActionOption,
    NarrativeCustomActionPolicy,
    NarrativeScope,
    NarrativeTurnPlan,
    SCHEMA_VERSION,
)
from system.narrative_turn_context import (
    NarrativeTurnContextSnapshot,
    PLANNER_REVISION,
    _stable_fingerprint,
)


@dataclass(frozen=True)
class _CandidateAction:
    """Internal candidate before scoring and selection."""
    intent: str
    action_type: ActionType
    display_text: str
    category: str
    evidence: tuple[str, ...]
    base_score: int
    expected_costs: tuple[tuple[str, str], ...]
    expected_risks: tuple[tuple[str, str], ...]
    required_conditions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]


def _derive_chapter_goal(chapter_plan: dict[str, Any]) -> str:
    if not isinstance(chapter_plan, dict):
        return "advance_story"
    title = str(chapter_plan.get("title") or chapter_plan.get("chapter_title") or "")
    if title:
        return f"chapter_{_hash_str(title)[:8]}_goal"
    return "advance_story"


def _derive_conflicts(planning_data: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts = planning_data.get("conflicts", [])
    if isinstance(conflicts, list):
        return [c for c in conflicts if isinstance(c, dict)]
    return []


def _derive_plot_threads(planning_data: dict[str, Any]) -> list[dict[str, Any]]:
    threads = planning_data.get("plot_threads", [])
    if isinstance(threads, list):
        return [t for t in threads if isinstance(t, dict)]
    return []


def _derive_active_threads(threads: list[dict[str, Any]]) -> list[str]:
    result = []
    for t in threads:
        status = str(t.get("status", "")).lower()
        if status in ("active", "open", "unresolved"):
            tid = str(t.get("thread_id") or t.get("id") or "")
            if tid:
                result.append(tid)
    return result


def _derive_characters(character_data: dict[str, Any]) -> list[dict[str, Any]]:
    chars = []
    for key in ("main_characters", "supporting_characters"):
        lst = character_data.get(key, [])
        if isinstance(lst, list):
            chars.extend(c for c in lst if isinstance(c, dict))
    return chars


def _derive_character_names(characters: list[dict[str, Any]]) -> list[str]:
    names = []
    for c in characters:
        name = str(c.get("name") or "")
        if name:
            names.append(name)
    return names


def _derive_world_rules(world_data: dict[str, Any]) -> list[str]:
    rules = []
    core = world_data.get("core_rules", [])
    if isinstance(core, list):
        for r in core:
            if isinstance(r, dict):
                rule_text = str(r.get("rule") or r.get("id") or "")
                if rule_text:
                    rules.append(rule_text)
    taboos = world_data.get("taboos_or_limits", [])
    if isinstance(taboos, list):
        for t in taboos:
            if isinstance(t, str):
                rules.append(t)
    return rules


def _derive_locations(world_data: dict[str, Any]) -> list[str]:
    locs = world_data.get("locations", [])
    names = []
    if isinstance(locs, list):
        for loc in locs:
            if isinstance(loc, dict):
                name = str(loc.get("name") or loc.get("location_name") or loc.get("id") or "")
                if name:
                    names.append(name)
    return names


def _hash_str(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _make_action_id(
    planner_rev: str,
    context_fp: str,
    intent: str,
    action_type: str,
    order: int,
) -> str:
    raw = f"{planner_rev}|{context_fp}|{intent}|{action_type}|{order}"
    return f"act_{_hash_str(raw)[:16]}"


def _make_turn_id(
    planner_rev: str,
    context_fp: str,
    parent_turn_id: str | None,
) -> str:
    raw = f"{planner_rev}|{context_fp}|{parent_turn_id or 'root'}"
    return f"turn_{_hash_str(raw)[:16]}"


def _generate_candidates(snapshot: NarrativeTurnContextSnapshot) -> list[_CandidateAction]:
    """Generate candidate actions from structured evidence.

    Each candidate is grounded in at least one real evidence source.
    Categories are chosen for semantic diversity.
    """
    candidates: list[_CandidateAction] = []
    chapter_plan = snapshot.chapter_plan_dict()
    planning = snapshot.planning_data_dict()
    characters = _derive_characters(snapshot.character_data_dict())
    char_names = _derive_character_names(characters)
    world_data = snapshot.world_data_dict()
    world_rules = _derive_world_rules(world_data)
    locations = _derive_locations(world_data)
    conflicts = _derive_conflicts(planning)
    threads = _derive_plot_threads(planning)
    active_threads = _derive_active_threads(threads)
    chapter_goal = _derive_chapter_goal(chapter_plan)

    # --- ADVANCE candidates ---
    if chapter_plan:
        evidence = ["CHAPTER_PLAN_BOUND"]
        title = str(chapter_plan.get("title") or chapter_plan.get("chapter_title") or "当前目标")
        candidates.append(_CandidateAction(
            intent=f"advance_{chapter_goal}",
            action_type=ActionType.ADVANCE,
            display_text=f"推进本章目标：{title}",
            category="advance_goal",
            evidence=tuple(evidence),
            base_score=80,
            expected_costs=(("time", "medium"), ("resource", "low")),
            expected_risks=(("unexpected_obstacle", "medium"),),
            required_conditions=("chapter_plan_available",),
            unavailable_reasons=(),
        ))
    else:
        candidates.append(_CandidateAction(
            intent="advance_story",
            action_type=ActionType.ADVANCE,
            display_text="推进故事发展",
            category="advance_generic",
            evidence=(),
            base_score=30,
            expected_costs=(("time", "low"),),
            expected_risks=(("direction_unknown", "high"),),
            required_conditions=(),
            unavailable_reasons=("CONTEXT_INSUFFICIENT", "chapter_plan_missing"),
        ))

    # --- INVESTIGATE candidates ---
    if active_threads:
        tid = active_threads[0]
        thread_info = next((t for t in threads if str(t.get("thread_id") or t.get("id")) == tid), {})
        thread_title = str(thread_info.get("title") or thread_info.get("name") or tid)
        candidates.append(_CandidateAction(
            intent=f"investigate_thread_{tid}",
            action_type=ActionType.INVESTIGATE,
            display_text=f"调查未解决线索：{thread_title}",
            category="investigate_thread",
            evidence=("PLOT_THREAD_ACTIVE",),
            base_score=70,
            expected_costs=(("time", "high"),),
            expected_risks=(("discovery_risks_safety", "medium"),),
            required_conditions=("active_plot_thread",),
            unavailable_reasons=(),
        ))
    elif conflicts:
        c0 = conflicts[0]
        ctitle = str(c0.get("title") or c0.get("conflict_name") or c0.get("conflict_id") or "核心冲突")
        candidates.append(_CandidateAction(
            intent=f"investigate_conflict",
            action_type=ActionType.INVESTIGATE,
            display_text=f"调查冲突根源：{ctitle}",
            category="investigate_conflict",
            evidence=("CONFLICT_IDENTIFIED",),
            base_score=65,
            expected_costs=(("time", "high"),),
            expected_risks=(("escalation", "medium"),),
            required_conditions=("conflict_identified",),
            unavailable_reasons=(),
        ))
    else:
        candidates.append(_CandidateAction(
            intent="investigate_surroundings",
            action_type=ActionType.INVESTIGATE,
            display_text="调查周围环境",
            category="investigate_generic",
            evidence=(),
            base_score=25,
            expected_costs=(("time", "medium"),),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=("CONTEXT_INSUFFICIENT", "no_identified_thread_or_conflict"),
        ))

    # --- RETREAT candidates ---
    if world_rules:
        rule_hint = world_rules[0][:20] if world_rules else ""
        candidates.append(_CandidateAction(
            intent="retreat_for_safety",
            action_type=ActionType.RETREAT,
            display_text="暂时撤退到安全区域，评估当前局势",
            category="retreat_safety",
            evidence=("WORLD_RULES_PRESENT",) if world_rules else (),
            base_score=50,
            expected_costs=(("time", "low"), ("momentum", "medium")),
            expected_risks=(("missed_opportunity", "medium"),),
            required_conditions=(),
            unavailable_reasons=(),
        ))
    else:
        candidates.append(_CandidateAction(
            intent="retreat_cautious",
            action_type=ActionType.RETREAT,
            display_text="谨慎观察，等待更多信息",
            category="retreat_cautious",
            evidence=(),
            base_score=20,
            expected_costs=(("time", "low"),),
            expected_risks=(("stagnation", "medium"),),
            required_conditions=(),
            unavailable_reasons=("CONTEXT_INSUFFICIENT",),
        ))

    # --- NEGOTIATE candidates (if characters available) ---
    if len(char_names) >= 2:
        target = char_names[1] if len(char_names) > 1 else char_names[0]
        candidates.append(_CandidateAction(
            intent=f"negotiate_with_{_hash_str(target)[:8]}",
            action_type=ActionType.NEGOTIATE,
            display_text=f"尝试与{target}谈判，寻求合作可能",
            category="negotiate_character",
            evidence=("CHARACTER_DATA_PRESENT",),
            base_score=55,
            expected_costs=(("relationship_uncertainty", "medium"),),
            expected_risks=(("rejection", "medium"), ("reveal_hand", "low")),
            required_conditions=("target_character_known",),
            unavailable_reasons=(),
        ))

    # --- SACRIFICE candidates (if resources present) ---
    resources = world_data.get("resources", {})
    if isinstance(resources, dict) and resources:
        res_keys = sorted(resources.keys())[:1]
        res_name = res_keys[0] if res_keys else "资源"
        candidates.append(_CandidateAction(
            intent=f"sacrifice_{res_name}",
            action_type=ActionType.SACRIFICE,
            display_text=f"牺牲{res_name}以换取关键突破",
            category="sacrifice_resource",
            evidence=("RESOURCE_DATA_PRESENT",),
            base_score=40,
            expected_costs=((res_name, "high"),),
            expected_risks=(("permanent_loss", "high"), ("unintended_consequences", "medium")),
            required_conditions=("resource_available",),
            unavailable_reasons=(),
        ))

    # --- Location-based investigate ---
    if locations:
        loc = locations[0]
        candidates.append(_CandidateAction(
            intent=f"investigate_location_{_hash_str(loc)[:8]}",
            action_type=ActionType.INVESTIGATE,
            display_text=f"前往{loc}实地调查",
            category="investigate_location",
            evidence=("LOCATION_KNOWN",),
            base_score=60,
            expected_costs=(("time", "high"), ("travel", "medium")),
            expected_risks=(("environmental", "low"),),
            required_conditions=("location_accessible",),
            unavailable_reasons=(),
        ))

    # --- Character-capability advance ---
    if characters and char_names:
        main = char_names[0]
        candidates.append(_CandidateAction(
            intent=f"advance_using_{_hash_str(main)[:8]}_skill",
            action_type=ActionType.ADVANCE,
            display_text=f"依靠{main}的能力突破当前局面",
            category="advance_character_skill",
            evidence=("CHARACTER_DATA_PRESENT",),
            base_score=65,
            expected_costs=(("stamina", "medium"),),
            expected_risks=(("overexertion", "low"),),
            required_conditions=("main_character_known",),
            unavailable_reasons=(),
        ))

    return candidates


def _score_candidate(
    candidate: _CandidateAction,
    snapshot: NarrativeTurnContextSnapshot | None,
) -> int:
    """Deterministic scoring based on evidence and category diversity.

    Score components:
    - base_score: intrinsic category weight
    - evidence_bonus: +5 per evidence code
    - goal_alignment: +15 if advance and chapter_plan bound
    - safety_penalty: -10 if high risk and no evidence
    """
    score = candidate.base_score
    score += len(candidate.evidence) * 5

    if snapshot is not None:
        if candidate.action_type == ActionType.ADVANCE and snapshot.chapter_plan_dict():
            score += 15

        if candidate.action_type == ActionType.INVESTIGATE and snapshot.planning_data_dict().get("plot_threads"):
            score += 10

    # Unavailable actions score very low
    if candidate.unavailable_reasons:
        score -= 40
        if "CONTEXT_INSUFFICIENT" in candidate.unavailable_reasons:
            score -= 20

    return score


def _select_top_3(
    candidates: list[_CandidateAction],
    context_fp: str,
    planner_rev: str,
) -> tuple[NarrativeActionOption, ...]:
    """Select exactly 3 actions with semantic diversity.

    Selection rules (deterministic):
    1. Sort all candidates by score desc, then by intent asc (deterministic tiebreak)
    2. Greedily pick top candidates, preferring action_type diversity
    3. If we don't have 3, fill with conservative placeholders
    4. Assign deterministic_order 1, 2, 3
    """
    scored = [
        (_score_candidate(c, None) if False else _compute_score(c), c)
        for c in candidates
    ]
    # Sort: score desc, then intent asc (stable, deterministic)
    scored.sort(key=lambda x: (-x[0], x[1].intent))

    # Greedy selection with type diversity
    selected: list[_CandidateAction] = []
    used_types: set[ActionType] = set()

    # First pass: top by score, preferring new types
    for _score, cand in scored:
        if len(selected) >= 3:
            break
        if cand.action_type not in used_types:
            selected.append(cand)
            used_types.add(cand.action_type)

    # Second pass: fill remaining from top remaining (even if same type)
    if len(selected) < 3:
        for _score, cand in scored:
            if len(selected) >= 3:
                break
            if cand not in selected:
                selected.append(cand)

    # Third pass: if still fewer than 3, add conservative placeholders
    while len(selected) < 3:
        idx = len(selected)
        placeholder = _CandidateAction(
            intent=f"conservative_hold_{idx}",
            action_type=ActionType.RETREAT,
            display_text="保持当前状态，等待更多信息",
            category="conservative_placeholder",
            evidence=(),
            base_score=0,
            expected_costs=(),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=("CONTEXT_INSUFFICIENT", "insufficient_evidence_for_three_options"),
        )
        selected.append(placeholder)

    # Build action options
    options: list[NarrativeActionOption] = []
    for i, cand in enumerate(selected[:3], start=1):
        action_id = _make_action_id(
            planner_rev, context_fp, cand.intent, cand.action_type.value, i
        )
        options.append(NarrativeActionOption(
            action_id=action_id,
            action_type=cand.action_type,
            display_text=cand.display_text,
            intent=cand.intent,
            expected_costs=cand.expected_costs,
            expected_risks=cand.expected_risks,
            required_conditions=cand.required_conditions,
            unavailable_reasons=cand.unavailable_reasons,
            provenance="deterministic-planner",
            deterministic_order=i,
        ))

    return tuple(options)


def _compute_score(candidate: _CandidateAction) -> int:
    """Score wrapper used during selection."""
    score = candidate.base_score
    score += len(candidate.evidence) * 5
    if candidate.unavailable_reasons:
        score -= 40
        if "CONTEXT_INSUFFICIENT" in candidate.unavailable_reasons:
            score -= 20
    return score


class NarrativeTurnPlanner:
    """Deterministic planner that builds NarrativeTurnPlan from context.

    Pure computation only. No writes. No Provider. No network.
    """

    REVISION = PLANNER_REVISION

    @staticmethod
    def build_plan(
        snapshot: NarrativeTurnContextSnapshot,
        *,
        parent_turn_id: str | None = None,
        clock_now: str,
    ) -> NarrativeTurnPlan:
        """Build a deterministic plan from a context snapshot.

        Args:
            snapshot: the bound context snapshot
            parent_turn_id: optional parent turn (for branching context)
            clock_now: injected ISO8601 UTC timestamp (not used for identity)

        Returns:
            Immutable NarrativeTurnPlan with exactly 3 recommended actions.
        """
        context_fp = snapshot.context_fingerprint
        planner_rev = snapshot.planner_revision

        candidates = _generate_candidates(snapshot)
        recommended = _select_top_3(candidates, context_fp, planner_rev)

        turn_id = _make_turn_id(planner_rev, context_fp, parent_turn_id)

        policy = NarrativeCustomActionPolicy(
            max_length=200,
            forbidden_patterns=("prompt_injection", "shell_injection", "path_traversal"),
            feasibility_pipeline=(
                "input_validation",
                "context_scope_binding",
                "source_revision_check",
                "branch_status_check",
                "action_structure_extraction",
                "world_rule_check",
                "canon_conflict_check",
                "character_capability_check",
                "resource_check",
                "location_check",
                "time_window_check",
                "relationship_permission_check",
                "dependency_check",
                "cost_risk_classification",
            ),
        )

        return NarrativeTurnPlan(
            schema_version=SCHEMA_VERSION,
            turn_id=turn_id,
            scope=snapshot.scope,
            chapter_id=snapshot.chapter_id,
            source_version_id=snapshot.source_version_id,
            parent_turn_id=parent_turn_id,
            context_fingerprint=context_fp,
            planning_revision=snapshot.planning_revision,
            canon_revision=snapshot.canon_revision,
            created_at=clock_now,
            recommended_actions=recommended,
            custom_action_policy=policy,
        )
