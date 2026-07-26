"""Action Feasibility Engine — deterministic 14-step pipeline.

Phase 0D4-B: validates recommended and custom actions against narrative
context. Pure computation only — no writes, no Provider, no network.

Pipeline order (strict — earlier blockers prevent later checks):
    1. input validation
    2. context/scope binding
    3. source and revision freshness
    4. branch status
    5. action structure extraction
    6. world-rule check
    7. Canon conflict check
    8. character capability check
    9. resource check
    10. location check
    11. time-window check
    12. relationship/permission check
    13. dependency check
    14. cost/risk classification
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from core.contracts.narrative_turn import (
    ActionSource,
    ActionType,
    NarrativeActionOption,
    NarrativeActionValidation,
    NarrativeScope,
    NarrativeTurnError,
    SCHEMA_VERSION,
    ValidationStatus,
)
from system.narrative_turn_context import NarrativeTurnContextSnapshot, _stable_fingerprint


MAX_CUSTOM_ACTION_LENGTH = 200


# ----------------------------------------------------------------------
# Reason codes — shared across the pipeline
# ----------------------------------------------------------------------
REASON_ACTION_EMPTY = "ACTION_EMPTY"
REASON_ACTION_TOO_LONG = "ACTION_TOO_LONG"
REASON_ACTION_UNPARSEABLE = "ACTION_UNPARSEABLE"
REASON_ACTION_TARGET_AMBIGUOUS = "ACTION_TARGET_AMBIGUOUS"
REASON_ACTION_OBJECT_AMBIGUOUS = "ACTION_OBJECT_AMBIGUOUS"
REASON_CONTEXT_STALE = "CONTEXT_STALE"
REASON_SOURCE_STALE = "SOURCE_STALE"
REASON_CANON_CONFLICT = "CANON_CONFLICT"
REASON_WORLD_RULE_CONFLICT = "WORLD_RULE_CONFLICT"
REASON_CAPABILITY_MISSING = "CAPABILITY_MISSING"
REASON_RESOURCE_MISSING = "RESOURCE_MISSING"
REASON_RESOURCE_COST_HIGH = "RESOURCE_COST_HIGH"
REASON_LOCATION_MISMATCH = "LOCATION_MISMATCH"
REASON_TIME_WINDOW_CLOSED = "TIME_WINDOW_CLOSED"
REASON_RELATIONSHIP_PERMISSION_MISSING = "RELATIONSHIP_PERMISSION_MISSING"
REASON_DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
REASON_BRANCH_NOT_ACTIVE = "BRANCH_NOT_ACTIVE"
REASON_BRANCH_ARCHIVED = "BRANCH_ARCHIVED"
REASON_CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"


STATUS_PRIORITY = {
    ValidationStatus.BLOCKED: 4,
    ValidationStatus.REQUIRES_CLARIFICATION: 3,
    ValidationStatus.ALLOWED_WITH_COST: 2,
    ValidationStatus.ALLOWED: 1,
}


def _worse_status(a: ValidationStatus, b: ValidationStatus) -> ValidationStatus:
    """Return the more severe of two statuses (blocked > clarification > cost > allowed)."""
    return a if STATUS_PRIORITY[a] >= STATUS_PRIORITY[b] else b


@dataclass(frozen=True)
class NormalizedCustomAction:
    """Result of custom action text normalization.

    The full text is never persisted — only its SHA-256 hash travels
    into the validation record.
    """

    normalized_text: str
    text_hash: str
    length: int

    @property
    def is_empty(self) -> bool:
        return not self.normalized_text


# ----------------------------------------------------------------------
# Normalization
# ----------------------------------------------------------------------
def normalize_custom_action(text: str) -> NormalizedCustomAction:
    """Normalize custom action input.

    Steps:
    - Reject None / non-string
    - Unicode NFKC
    - Strip leading/trailing whitespace
    - Collapse consecutive whitespace to single space
    - Reject NUL and control characters (except common ones)
    - Enforce length limit
    - Compute SHA-256 of normalized text

    Does NOT execute code, parse HTML, read paths, invoke shell, or
    call Provider. Natural-language "ignore previous instructions"
    style text is not blocked — it's just text.
    """
    if not isinstance(text, str):
        raise NarrativeTurnError(
            NarrativeTurnError.ACTION_INVALID,
            "Custom action must be a string",
        )

    # 1. Unicode NFKC normalization
    normalized = unicodedata.normalize("NFKC", text)

    # 2. Strip
    normalized = normalized.strip()

    # 3. Collapse whitespace (spaces, tabs, newlines → single space)
    normalized = re.sub(r"\s+", " ", normalized)

    # 4. Reject NUL
    if "\x00" in normalized:
        raise NarrativeTurnError(
            NarrativeTurnError.ACTION_INVALID,
            "Custom action contains NUL character",
        )

    # 5. Reject unacceptable control characters (allow common whitespace only after collapse)
    for ch in normalized:
        if unicodedata.category(ch).startswith("C") and ch not in (" ",):
            # Allow space (which is Zs category, not C). Block Cc/Cf/etc.
            raise NarrativeTurnError(
                NarrativeTurnError.ACTION_INVALID,
                f"Custom action contains control character: U+{ord(ch):04X}",
            )

    # 6. Length check
    if not normalized:
        raise NarrativeTurnError(
            NarrativeTurnError.ACTION_INVALID,
            REASON_ACTION_EMPTY,
        )
    if len(normalized) > MAX_CUSTOM_ACTION_LENGTH:
        raise NarrativeTurnError(
            NarrativeTurnError.ACTION_INVALID,
            f"{REASON_ACTION_TOO_LONG}: max {MAX_CUSTOM_ACTION_LENGTH}, got {len(normalized)}",
        )

    text_hash = sha256(normalized.encode("utf-8")).hexdigest()
    return NormalizedCustomAction(
        normalized_text=normalized,
        text_hash=text_hash,
        length=len(normalized),
    )


# ----------------------------------------------------------------------
# Action structure extraction (deterministic, keyword-based)
# ----------------------------------------------------------------------
_ACTION_VERBS = {
    "去": "go",
    "前往": "go",
    "到": "go",
    "抵达": "go",
    "调查": "investigate",
    "探查": "investigate",
    "检查": "investigate",
    "查看": "investigate",
    "寻找": "investigate",
    "搜索": "investigate",
    "攻击": "attack",
    "使用": "use",
    "拿": "use",
    "用": "use",
    "和": "talk",
    "与": "talk",
    "跟": "talk",
    "对话": "talk",
    "谈判": "negotiate",
    "谈": "negotiate",
    "撤退": "retreat",
    "退回": "retreat",
    "后撤": "retreat",
    "等": "wait",
    "等待": "wait",
    "休息": "rest",
    "推进": "advance",
    "前进": "advance",
}

_EN_VERBS = {
    "go": "go",
    "travel": "go",
    "head": "go",
    "investigate": "investigate",
    "search": "investigate",
    "look": "investigate",
    "check": "investigate",
    "examine": "investigate",
    "attack": "attack",
    "fight": "attack",
    "use": "use",
    "take": "use",
    "talk": "talk",
    "speak": "talk",
    "negotiate": "negotiate",
    "retreat": "retreat",
    "flee": "retreat",
    "wait": "wait",
    "rest": "rest",
    "advance": "advance",
    "proceed": "advance",
}


@dataclass(frozen=True)
class _ActionStructure:
    verb: str | None
    target: str | None
    object_name: str | None
    location_name: str | None
    character_name: str | None


def _extract_structure(
    text: str,
    known_characters: list[str],
    known_locations: list[str],
    known_resources: list[str],
) -> _ActionStructure:
    """Deterministic, keyword-based structure extraction.

    Returns a structure with None for any unrecognized field.
    Never guesses — if ambiguous, leaves it None so the pipeline
    can classify it as requires_clarification.
    """
    verb: str | None = None
    target: str | None = None
    object_name: str | None = None
    location_name: str | None = None
    character_name: str | None = None

    # Match Chinese verbs at the beginning
    for zh_verb, eng in sorted(_ACTION_VERBS.items(), key=lambda x: -len(x[0])):
        if text.startswith(zh_verb):
            verb = eng
            break
    if verb is None:
        lower_text = text.lower()
        for en_verb in sorted(_EN_VERBS.keys(), key=lambda x: -len(x)):
            if lower_text.startswith(en_verb):
                verb = _EN_VERBS[en_verb]
                break

    # Check for known characters
    matched_chars = [c for c in known_characters if c and c in text]
    if len(matched_chars) == 1:
        character_name = matched_chars[0]
        target = character_name
    elif len(matched_chars) > 1:
        character_name = None  # ambiguous
        target = None

    # Check for known locations
    matched_locs = [loc for loc in known_locations if loc and loc in text]
    if len(matched_locs) == 1:
        location_name = matched_locs[0]
        if not target:
            target = location_name
    elif len(matched_locs) > 1:
        location_name = None  # ambiguous

    # Check for known resources/objects
    matched_res = [r for r in known_resources if r and r in text]
    if len(matched_res) == 1:
        object_name = matched_res[0]
    elif len(matched_res) > 1:
        object_name = None  # ambiguous

    return _ActionStructure(
        verb=verb,
        target=target,
        object_name=object_name,
        location_name=location_name,
        character_name=character_name,
    )


# ----------------------------------------------------------------------
# Validation accumulator
# ----------------------------------------------------------------------
@dataclass
class _ValidationBuilder:
    status: ValidationStatus = ValidationStatus.ALLOWED
    blocking_reasons: list[str] = None  # type: ignore[assignment]
    cost_explanation: list[tuple[str, str]] = None  # type: ignore[assignment]
    risk_explanation: list[tuple[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.blocking_reasons is None:
            self.blocking_reasons = []
        if self.cost_explanation is None:
            self.cost_explanation = []
        if self.risk_explanation is None:
            self.risk_explanation = []

    def upgrade(self, new_status: ValidationStatus, reason: str) -> None:
        if STATUS_PRIORITY[new_status] > STATUS_PRIORITY[self.status]:
            self.status = new_status
        self.blocking_reasons.append(reason)

    def add_cost(self, kind: str, level: str) -> None:
        self.cost_explanation.append((kind, level))

    def add_risk(self, kind: str, level: str) -> None:
        self.risk_explanation.append((kind, level))

    def is_blocked(self) -> bool:
        return self.status == ValidationStatus.BLOCKED


# ----------------------------------------------------------------------
# Feasibility Engine
# ----------------------------------------------------------------------
class NarrativeActionFeasibility:
    """Deterministic feasibility engine.

    Pure computation only. No writes. No Provider. No network.
    """

    @staticmethod
    def validate_recommended(
        snapshot: NarrativeTurnContextSnapshot,
        action: NarrativeActionOption,
        turn_id: str,
        *,
        clock_now: str,
    ) -> NarrativeActionValidation:
        """Validate a recommended action against context.

        Follows the strict 14-step pipeline.
        """
        builder = _ValidationBuilder()

        # Step 1: input validation
        if action.unavailable_reasons:
            builder.upgrade(
                ValidationStatus.REQUIRES_CLARIFICATION,
                REASON_CONTEXT_INSUFFICIENT,
            )
            for reason in action.unavailable_reasons:
                builder.blocking_reasons.append(str(reason))

        # Step 2: context/scope binding (implicit — call passes snapshot)
        if not snapshot.chapter_plan_dict() and not snapshot.planning_data_dict().get("chapters"):
            builder.upgrade(
                ValidationStatus.REQUIRES_CLARIFICATION,
                REASON_CONTEXT_INSUFFICIENT,
            )

        # Step 3: source and revision freshness (stale if no source)
        if not snapshot.source_fingerprint or snapshot.source_fingerprint == _stable_fingerprint(""):
            builder.upgrade(
                ValidationStatus.REQUIRES_CLARIFICATION,
                REASON_SOURCE_STALE,
            )

        # Step 4: branch status
        if not snapshot.branch_is_active:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_BRANCH_NOT_ACTIVE)
        if not snapshot.branch_open:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_BRANCH_ARCHIVED)

        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot,
                turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None,
                builder=builder,
                clock_now=clock_now,
            )

        # Step 5: action structure extraction
        structure = _extract_structure(
            action.display_text,
            known_characters=_known_character_names(snapshot),
            known_locations=_known_location_names(snapshot),
            known_resources=_known_resource_names(snapshot),
        )

        # Steps 6-13: contextual checks
        _world_rule_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _canon_conflict_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _capability_check(builder, snapshot, structure, action)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _resource_check(builder, snapshot, structure, action)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _location_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _time_window_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _relationship_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=action.action_id,
                custom_action_text_hash=None, builder=builder, clock_now=clock_now,
            )

        _dependency_check(builder, snapshot, action)

        # Step 14: cost/risk classification
        _classify_costs_and_risks(builder, action)

        return _build_validation_record(
            snapshot=snapshot,
            turn_id=turn_id,
            action_source=ActionSource.RECOMMENDED,
            selected_action_id=action.action_id,
            custom_action_text_hash=None,
            builder=builder,
            clock_now=clock_now,
        )

    @staticmethod
    def validate_custom(
        snapshot: NarrativeTurnContextSnapshot,
        normalized_action: NormalizedCustomAction,
        turn_id: str,
        *,
        clock_now: str,
    ) -> NarrativeActionValidation:
        """Validate a custom (user-entered) action against context."""
        builder = _ValidationBuilder()

        # Step 1: input validation
        if normalized_action.is_empty:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_ACTION_EMPTY)
        if normalized_action.length > MAX_CUSTOM_ACTION_LENGTH:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_ACTION_TOO_LONG)

        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        # Step 2: context/scope binding
        if not snapshot.chapter_plan_dict() and not snapshot.planning_data_dict().get("chapters"):
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_CONTEXT_INSUFFICIENT)

        # Step 3: source freshness
        if not snapshot.source_fingerprint or snapshot.source_fingerprint == _stable_fingerprint(""):
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_SOURCE_STALE)

        # Step 4: branch status
        if not snapshot.branch_is_active:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_BRANCH_NOT_ACTIVE)
        if not snapshot.branch_open:
            builder.upgrade(ValidationStatus.BLOCKED, REASON_BRANCH_ARCHIVED)

        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        # Step 5: action structure extraction
        structure = _extract_structure(
            normalized_action.normalized_text,
            known_characters=_known_character_names(snapshot),
            known_locations=_known_location_names(snapshot),
            known_resources=_known_resource_names(snapshot),
        )

        if structure.verb is None and structure.target is None and structure.object_name is None:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_UNPARSEABLE)

        # Check ambiguity
        text = normalized_action.normalized_text
        chars = _known_character_names(snapshot)
        locs = _known_location_names(snapshot)
        reses = _known_resource_names(snapshot)
        matched_chars = [c for c in chars if c in text]
        matched_locs = [loc for loc in locs if loc in text]
        matched_res = [r for r in reses if r in text]

        if structure.target is None and (
            "他" in text or "她" in text or "它" in text or "那个" in text
        ):
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_TARGET_AMBIGUOUS)
        if structure.object_name is None and "那个东西" in text:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_OBJECT_AMBIGUOUS)

        if len(matched_chars) > 1:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_TARGET_AMBIGUOUS)
        if len(matched_locs) > 1 and structure.location_name is None:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_TARGET_AMBIGUOUS)
        if len(matched_res) > 1 and structure.object_name is None:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_OBJECT_AMBIGUOUS)

        # Steps 6-13
        _world_rule_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _canon_conflict_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _capability_check_custom(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _resource_check_custom(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _location_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _time_window_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        _relationship_check(builder, snapshot, structure)
        if builder.is_blocked():
            return _build_validation_record(
                snapshot=snapshot, turn_id=turn_id,
                action_source=ActionSource.CUSTOM,
                selected_action_id=None,
                custom_action_text_hash=normalized_action.text_hash,
                builder=builder, clock_now=clock_now,
            )

        # Dependency check (custom has no plan-dep check, skip)
        # Step 14: cost/risk classification
        _classify_costs_custom(builder, structure, snapshot)

        return _build_validation_record(
            snapshot=snapshot,
            turn_id=turn_id,
            action_source=ActionSource.CUSTOM,
            selected_action_id=None,
            custom_action_text_hash=normalized_action.text_hash,
            builder=builder,
            clock_now=clock_now,
        )


# ----------------------------------------------------------------------
# Helper functions for pipeline steps
# ----------------------------------------------------------------------
def _known_character_names(snapshot: NarrativeTurnContextSnapshot) -> list[str]:
    data = snapshot.character_data_dict()
    names = []
    for key in ("main_characters", "supporting_characters"):
        lst = data.get(key, [])
        if isinstance(lst, list):
            for c in lst:
                if isinstance(c, dict):
                    name = str(c.get("name") or "")
                    if name:
                        names.append(name)
    return names


def _known_location_names(snapshot: NarrativeTurnContextSnapshot) -> list[str]:
    data = snapshot.world_data_dict().get("locations", [])
    names = []
    if isinstance(data, list):
        for loc in data:
            if isinstance(loc, dict):
                name = str(loc.get("name") or loc.get("location_name") or "")
                if name:
                    names.append(name)
    return names


def _known_resource_names(snapshot: NarrativeTurnContextSnapshot) -> list[str]:
    resources = snapshot.world_data_dict().get("resources", {})
    if isinstance(resources, dict):
        return sorted(resources.keys())
    return []


def _world_rule_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 6: world-rule check.

    Only blocks if we have explicit world rules AND the action verb
    is explicitly in the taboos list.
    """
    taboos = snapshot.world_data_dict().get("taboos_or_limits", [])
    if not isinstance(taboos, list) or not taboos:
        return
    if structure.verb is None:
        return
    for taboo in taboos:
        if isinstance(taboo, str) and structure.verb in taboo.lower():
            builder.upgrade(ValidationStatus.BLOCKED, REASON_WORLD_RULE_CONFLICT)
            return


def _canon_conflict_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 7: Canon conflict check.

    In 0D4-B we only check explicit canon-conflict markers in the
    chapter plan. Deeper Canon integration comes in later phases.
    """
    chapter_plan = snapshot.chapter_plan_dict()
    if not isinstance(chapter_plan, dict):
        return
    canon_blocks = chapter_plan.get("canon_blocked_actions", [])
    if not isinstance(canon_blocks, list):
        return
    for blocked in canon_blocks:
        if isinstance(blocked, dict):
            verb = str(blocked.get("verb") or "")
            target = str(blocked.get("target") or "")
            if verb and structure.verb and verb.lower() == structure.verb.lower():
                if not target or (target and structure.target and target in structure.target):
                    builder.upgrade(ValidationStatus.BLOCKED, REASON_CANON_CONFLICT)
                    return
        elif isinstance(blocked, str):
            if structure.verb and structure.verb in blocked.lower():
                builder.upgrade(ValidationStatus.BLOCKED, REASON_CANON_CONFLICT)
                return


def _capability_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
    action: NarrativeActionOption,
) -> None:
    """Step 8: character capability check for recommended actions."""
    if "main_character_known" not in action.required_conditions:
        return
    chars = _known_character_names(snapshot)
    if not chars:
        builder.upgrade(ValidationStatus.BLOCKED, REASON_CAPABILITY_MISSING)


def _capability_check_custom(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 8: character capability check for custom actions.

    If the action mentions a specific character not in the known list,
    flag as target_ambiguous. Otherwise, assume main character can act
    (conservative allowance).
    """
    if structure.character_name is None and structure.verb in ("talk", "negotiate"):
        # No character target identified for a social action
        chars = _known_character_names(snapshot)
        if not chars:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_TARGET_AMBIGUOUS)


def _resource_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
    action: NarrativeActionOption,
) -> None:
    """Step 9: resource check for recommended actions."""
    if "resource_available" not in action.required_conditions:
        return
    resources = _known_resource_names(snapshot)
    if not resources:
        builder.upgrade(ValidationStatus.BLOCKED, REASON_RESOURCE_MISSING)


def _resource_check_custom(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 9: resource check for custom actions."""
    if structure.object_name is not None:
        resources = _known_resource_names(snapshot)
        if structure.object_name not in resources:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_RESOURCE_MISSING)


def _location_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 10: location check."""
    if structure.verb == "go" and structure.location_name is None:
        locs = _known_location_names(snapshot)
        if not locs:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_LOCATION_MISMATCH)
        else:
            # Multiple locations but none identified → ambiguous
            if len(locs) >= 2 and structure.target is None:
                builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_ACTION_TARGET_AMBIGUOUS)


def _time_window_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 11: time-window check.

    In 0D4-B we only check rolling window constraints at a basic level.
    """
    rolling = snapshot.rolling_window_dict()
    if not isinstance(rolling, dict):
        return
    remaining = rolling.get("remaining_chapters") or rolling.get("remaining_turns")
    if isinstance(remaining, (int, float)) and remaining <= 0:
        if structure.verb in ("advance", "investigate"):
            builder.upgrade(ValidationStatus.BLOCKED, REASON_TIME_WINDOW_CLOSED)


def _relationship_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    structure: _ActionStructure,
) -> None:
    """Step 12: relationship/permission check."""
    if structure.verb == "negotiate" and structure.character_name is None:
        chars = _known_character_names(snapshot)
        if len(chars) >= 2:
            builder.upgrade(
                ValidationStatus.REQUIRES_CLARIFICATION,
                REASON_RELATIONSHIP_PERMISSION_MISSING,
            )


def _dependency_check(
    builder: _ValidationBuilder,
    snapshot: NarrativeTurnContextSnapshot,
    action: NarrativeActionOption,
) -> None:
    """Step 13: dependency check."""
    deps = snapshot.dependencies_dict()
    if not isinstance(deps, dict):
        return
    # If the action targets a thread and that thread has unresolved deps, flag
    # (Conservative: only block if explicitly marked as blocking dependency)
    blocking = deps.get("blocking_dependencies", [])
    if isinstance(blocking, list) and len(blocking) > 0:
        if action.action_type == ActionType.ADVANCE:
            builder.upgrade(ValidationStatus.REQUIRES_CLARIFICATION, REASON_DEPENDENCY_BLOCKED)


def _classify_costs_and_risks(
    builder: _ValidationBuilder,
    action: NarrativeActionOption,
) -> None:
    """Step 14: cost/risk classification for recommended actions."""
    if builder.status == ValidationStatus.ALLOWED:
        has_costs = False
        for cost_kind, cost_level in action.expected_costs:
            builder.add_cost(str(cost_kind), str(cost_level))
            if str(cost_level).lower() in ("high", "severe"):
                has_costs = True
        for risk_kind, risk_level in action.expected_risks:
            builder.add_risk(str(risk_kind), str(risk_level))
        if has_costs:
            builder.upgrade(ValidationStatus.ALLOWED_WITH_COST, REASON_RESOURCE_COST_HIGH)


def _classify_costs_custom(
    builder: _ValidationBuilder,
    structure: _ActionStructure,
    snapshot: NarrativeTurnContextSnapshot,
) -> None:
    """Step 14: cost/risk classification for custom actions."""
    if builder.status == ValidationStatus.ALLOWED:
        if structure.verb == "go":
            builder.add_cost("time", "medium")
            builder.add_cost("travel", "low")
        elif structure.verb == "investigate":
            builder.add_cost("time", "high")
            builder.add_risk("discovery", "medium")
        elif structure.verb == "attack":
            builder.add_cost("stamina", "high")
            builder.add_risk("injury", "high")
            builder.upgrade(ValidationStatus.ALLOWED_WITH_COST, REASON_RESOURCE_COST_HIGH)
        elif structure.verb == "negotiate":
            builder.add_cost("relationship_uncertainty", "medium")
            builder.add_risk("rejection", "medium")
        elif structure.verb == "retreat":
            builder.add_cost("momentum", "medium")
            builder.add_risk("missed_opportunity", "medium")
        elif structure.verb == "sacrifice":
            builder.add_cost("resource", "high")
            builder.add_risk("permanent_loss", "high")
            builder.upgrade(ValidationStatus.ALLOWED_WITH_COST, REASON_RESOURCE_COST_HIGH)
        else:
            builder.add_cost("time", "low")


def _build_validation_record(
    *,
    snapshot: NarrativeTurnContextSnapshot,
    turn_id: str,
    action_source: ActionSource,
    selected_action_id: str | None,
    custom_action_text_hash: str | None,
    builder: _ValidationBuilder,
    clock_now: str,
) -> NarrativeActionValidation:
    """Create the immutable validation record."""
    # Deterministic validation_id
    id_input = {
        "turn_id": turn_id,
        "action_source": action_source.value,
        "selected_action_id": selected_action_id,
        "custom_action_text_hash": custom_action_text_hash,
        "context_fingerprint": snapshot.context_fingerprint,
        "status": builder.status.value,
        "blocking_reasons": sorted(builder.blocking_reasons),
    }
    validation_id = f"val_{_stable_fingerprint(id_input)[:16]}"

    return NarrativeActionValidation(
        schema_version=SCHEMA_VERSION,
        validation_id=validation_id,
        turn_id=turn_id,
        scope=snapshot.scope,
        chapter_id=snapshot.chapter_id,
        action_source=action_source,
        selected_action_id=selected_action_id,
        custom_action_text_hash=custom_action_text_hash,
        status=builder.status,
        blocking_reasons=tuple(sorted(builder.blocking_reasons)),
        cost_explanation=tuple(
            (str(k), str(v)) for k, v in builder.cost_explanation
        ),
        risk_explanation=tuple(
            (str(k), str(v)) for k, v in builder.risk_explanation
        ),
        checked_at=clock_now,
        context_fingerprint=snapshot.context_fingerprint,
    )
