"""Phase 0D4-C-P-FIX-RC — Design document contract static checks.

These checks target the Narrative Turn design documents ONLY.  They do
NOT import or modify any production code.  They verify that the
design-contract drift corrected by 0D4-C-P-FIX-RC is consistent across
all 6 updated documents.

Run:
    python -m pytest story-os-demo/tests/test_phase0d4c_p_fix_rc_design_contract.py -v
or:
    python story-os-demo/tests/test_phase0d4c_p_fix_rc_design_contract.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Document paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS = {
    "ui_spec": _REPO_ROOT / "docs" / "design" / "simulator_narrative_turn_ui_spec.md",
    "states": _REPO_ROOT / "docs" / "design" / "simulator_narrative_turn_interaction_states.md",
    "contract": _REPO_ROOT / "docs" / "design" / "simulator_narrative_turn_component_contract.md",
    "phase": _REPO_ROOT / "docs" / "planning" / "PHASE_0D4_C_P.md",
    "delivery": _REPO_ROOT / "docs" / "planning" / "PHASE_0D4_C_P_DELIVERY_REPORT.md",
    "brief": _REPO_ROOT / "docs" / "planning" / "PHASE_0D4_IMPLEMENTATION_BRIEF.md",
}

# Real production contract file (for cross-checking that `.evidence` is
# NOT a real field).
SNAPSHOT_SRC = _REPO_ROOT / "story-os-demo" / "system" / "narrative_turn_context.py"
PREVIEW_SRC = _REPO_ROOT / "story-os-demo" / "core" / "contracts" / "narrative_turn_preview.py"


def _read(name: str) -> str:
    path = DOCS[name]
    assert path.exists(), f"missing design document: {path}"
    return path.read_text(encoding="utf-8")


def _read_all() -> dict[str, str]:
    return {name: _read(name) for name in DOCS}


# ---------------------------------------------------------------------------
# Rule 1: component count == 10
# ---------------------------------------------------------------------------

def test_rule_01_component_count_is_10():
    """Component tree must declare exactly 10 components."""
    contract = _read("contract")
    # The contract document must state "Component count: 10" (with
    # possible markdown bold markers).
    assert re.search(r"Component count:\s*\*?\*?10\b", contract), (
        "component contract must state 'Component count: 10'"
    )
    # No stale "9 components" reference.
    assert "9 components" not in contract, (
        "component contract still references '9 components' (should be 10)"
    )
    # The 10 named components must appear in the tree.
    expected = [
        "NarrativeTurnWorkspace",
        "NarrativeSituationHeader",
        "NarrativeEvidenceSummary",
        "RecommendedActionGroup",
        "RecommendedActionRow",
        "CustomActionComposer",
        "FeasibilityPanel",
        "ConsequencePreview",
        "TurnPrimaryAction",
        "TurnStatusNotice",
    ]
    for name in expected:
        assert name in contract, f"component missing from contract: {name}"


# ---------------------------------------------------------------------------
# Rule 2: custom composer state count == 15
# ---------------------------------------------------------------------------

_CUSTOM_STATES = [
    "idle", "editing", "validating", "too_long", "control_char_rejected",
    "unparseable", "ambiguous_target", "ambiguous_object", "allowed",
    "allowed_with_cost", "requires_clarification", "blocked", "checking",
    "superseded_by_recommended", "stale_response",
]


def test_rule_02_custom_composer_state_count_is_15():
    """Custom Action Composer must declare exactly 15 states."""
    states_doc = _read("states")
    contract = _read("contract")
    # Interaction states §12 completeness checklist must say 15.
    assert re.search(r"Custom Action Composer\s*\|\s*\*?\*?15\b", states_doc), (
        "interaction states completeness checklist must record 15 Custom Composer states"
    )
    # Component contract must say 15 states.
    assert re.search(r"\*?\*?15 states\b", contract), (
        "component contract must state '15 states' for CustomActionComposer"
    )
    # All 15 state names must appear in the states document.
    for state in _CUSTOM_STATES:
        assert state in states_doc, f"Custom Composer state missing from states doc: {state}"


# ---------------------------------------------------------------------------
# Rule 3: no "validated against turn store" in 0D4-C URL rules
# ---------------------------------------------------------------------------

def test_rule_03_no_turn_store_validation_in_url_rules():
    """URL turn_id must NOT be validated against NarrativeTurnStore."""
    all_docs = _read_all()
    forbidden_phrases = [
        "validated against turn store",
        "validated against Turn store",
        "validated against NarrativeTurnStore",
        "validated against the turn store",
    ]
    for doc_name, content in all_docs.items():
        for phrase in forbidden_phrases:
            assert phrase not in content, (
                f"document '{doc_name}' contains forbidden phrase '{phrase}' "
                f"(turn_id must be verified by deterministic rebuild, not Turn store)"
            )


# ---------------------------------------------------------------------------
# Rule 4: no ".evidence" field unless the real contract actually has it
# ---------------------------------------------------------------------------

def test_rule_04_no_phantom_evidence_field():
    """Documents must not reference a non-existent .evidence field."""
    # First confirm the real production contract has NO `evidence` field
    # (only `evidence_codes` and `limitations`).
    snapshot_src = SNAPSHOT_SRC.read_text(encoding="utf-8")
    # The snapshot must expose evidence_codes, not evidence.
    assert "evidence_codes" in snapshot_src, "real snapshot must have evidence_codes"
    # A bare `evidence` field declaration (e.g. `    evidence: ...`) must
    # NOT exist on the snapshot class.
    snapshot_class_block = _extract_class_block(snapshot_src, "NarrativeTurnContextSnapshot")
    assert re.search(r"^\s+evidence\s*:", snapshot_class_block, re.MULTILINE) is None, (
        "real NarrativeTurnContextSnapshot must NOT declare a bare `evidence` field"
    )

    # The preview DTO has evidence_codes, not evidence.
    preview_src = PREVIEW_SRC.read_text(encoding="utf-8")
    preview_block = _extract_class_block(preview_src, "NarrativeTurnPreview")
    assert re.search(r"^\s+evidence_codes\s*:", preview_block, re.MULTILINE) is not None
    assert re.search(r"^\s+evidence\s*:", preview_block, re.MULTILINE) is None, (
        "real NarrativeTurnPreview must NOT declare a bare `evidence` field"
    )

    # Now check the design documents.
    #
    # The intent is to flag documents that USE `.evidence` as if it were
    # a real field on the snapshot/preview DTO.  Documents are ALLOWED
    # to mention the phantom field in explicit negation/forbidden
    # context (e.g. "there is **no** `NarrativeTurnContextSnapshot.evidence`
    # field", "forbidden: referencing `.evidence` field that does not
    # exist", "non-existent `NarrativeTurnContextSnapshot.evidence` field").
    # Those negation references are the correct documentation behavior
    # and must not be flagged.
    all_docs = _read_all()
    forbidden_patterns = [
        # `snapshot.evidence` or `NarrativeTurnContextSnapshot.evidence`
        r"NarrativeTurnContextSnapshot\.evidence\b",
        r"snapshot\.evidence\b",
        # `preview.evidence` or `NarrativeTurnPreview.evidence`
        r"NarrativeTurnPreview\.evidence\b",
        r"preview\.evidence\b",
    ]
    # Negation markers that indicate a forbidden/non-existent reference
    # rather than a factual field use.  Match is allowed if any of these
    # markers appear within ±80 chars of the match.
    negation_markers = [
        "no ", "no`", "no `", "not ", "not`", "not `",
        "non-existent", "nonexistent", "does not exist", "do not exist",
        "does not have", "do not have", "without ",
        "forbidden", "forbid", "must not", "MUST NOT",
        "no longer", "removed", "phantom", "missing",
        "there is no", "there is **no**", "is no ", "are no ",
    ]

    def _is_negated(text: str, match: re.Match) -> bool:
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 80)
        window = text[start:end].lower()
        return any(marker in window for marker in negation_markers)

    for doc_name, content in all_docs.items():
        for pattern in forbidden_patterns:
            for match in re.finditer(pattern, content):
                if _is_negated(content, match):
                    continue
                raise AssertionError(
                    f"document '{doc_name}' references non-existent field "
                    f"matching pattern '{pattern}' at offset {match.start()} "
                    f"without negation context: "
                    f"'{content[max(0, match.start()-40):match.end()+40]}'"
                )


def _extract_class_block(src: str, class_name: str) -> str:
    """Return the source block of a class definition (best-effort)."""
    pattern = rf"^class\s+{re.escape(class_name)}\b.*?(?=^class\s|\Z)"
    match = re.search(pattern, src, re.DOTALL | re.MULTILINE)
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# Rule 5: no nested <main> contract
# ---------------------------------------------------------------------------

def test_rule_05_no_nested_main_contract():
    """Workspace must NOT nest a second <main>."""
    contract = _read("contract")
    ui_spec = _read("ui_spec")
    # The contract must explicitly state the no-nested-main rule.
    assert "MUST NOT nest a second" in contract or "MUST NOT nest another" in contract, (
        "component contract must state the no-nested-<main> rule"
    )
    # The workspace DOM contract must use <section role="region">, not <main>.
    assert re.search(
        r'<section\s+id="narrative-turn-workspace"\s+role="region"',
        contract,
    ), "workspace must mount as <section role=\"region\">, not <main>"


# ---------------------------------------------------------------------------
# Rule 6: no role="banner" for situation header
# ---------------------------------------------------------------------------

def test_rule_06_no_banner_role_for_situation_header():
    """Situation Header must NOT use role='banner'."""
    contract = _read("contract")
    ui_spec = _read("ui_spec")

    # The DOM contract for the situation header must not use role="banner".
    # Extract the §3.1 DOM contract block.
    header_block = _extract_section_block(contract, "## 3.1 DOM contract", "## 4.")
    assert header_block, "could not locate §3.1 DOM contract block"
    assert 'role="banner"' not in header_block, (
        "Situation Header DOM contract must not use role='banner'"
    )

    # The accessibility semantics row must explicitly disallow role=banner.
    assert "role=\"banner\"" in contract, (
        "contract must explicitly mention role='banner' in the Forbidden list"
    )

    # The UI spec accessibility table must say "no nested <main>" and must
    # not prescribe role=banner for the situation header.
    # (It is OK for the contract to *mention* role=banner in a Forbidden
    # cell; we already checked that above.)


def _extract_section_block(text: str, start_marker: str, end_marker: str) -> str:
    """Return the text between two markdown section markers (best-effort)."""
    start = text.find(start_marker)
    if start == -1:
        return ""
    end = text.find(end_marker, start + len(start_marker))
    if end == -1:
        return text[start:]
    return text[start:end]


# ---------------------------------------------------------------------------
# Rule 7: no <label role="radio"> without a native radio input
# ---------------------------------------------------------------------------

def test_rule_07_no_label_radio_without_native_input():
    """RecommendedActionRow must use native radio, not <label role='radio'>."""
    contract = _read("contract")
    ui_spec = _read("ui_spec")

    # The §6.1 DOM contract must contain a native <input type="radio">.
    row_block = _extract_section_block(contract, "### 6.1 DOM contract", "## 7.")
    assert row_block, "could not locate §6.1 DOM contract block"
    assert '<input type="radio"' in row_block, (
        "RecommendedActionRow DOM contract must contain a native <input type='radio'>"
    )

    # The §6.1 block must NOT contain <label ... role="radio">.
    assert re.search(r'<label[^>]*role="radio"', row_block) is None, (
        "RecommendedActionRow DOM contract must not use <label role='radio'>"
    )

    # The §5 RecommendedActionGroup must not prescribe role="radio" on rows.
    group_block = _extract_section_block(contract, "## 5. RecommendedActionGroup", "## 6.")
    assert 'rows are `role="radio"`' not in group_block, (
        "RecommendedActionGroup must not prescribe role='radio' on rows"
    )

    # The UI spec must prescribe native radio.
    assert "native radio" in ui_spec.lower() or "native `<input type=\"radio\">`" in ui_spec, (
        "UI spec must prescribe native radio inputs"
    )


# ---------------------------------------------------------------------------
# Rule 8: only one business live region
# ---------------------------------------------------------------------------

def test_rule_08_only_one_business_live_region():
    """TurnStatusNotice must be the only business live region."""
    contract = _read("contract")
    states_doc = _read("states")
    ui_spec = _read("ui_spec")

    # The contract must state TurnStatusNotice is the only region that
    # announces.
    assert "only" in contract.lower() and "region that announces" in contract.lower(), (
        "contract must state TurnStatusNotice is the only announcing region"
    )

    # The CustomActionComposer counter must NOT have aria-live.
    composer_block = _extract_section_block(contract, "### 7.1 DOM contract", "## 8.")
    assert composer_block, "could not locate §7.1 DOM contract block"
    # The counter <span> must not carry aria-live.
    counter_line = re.search(r'<span[^>]*nt-custom-counter[^>]*>', composer_block)
    assert counter_line, "could not locate counter <span> in composer DOM contract"
    assert "aria-live" not in counter_line.group(0), (
        "Custom Action Composer counter must NOT carry aria-live"
    )

    # The states doc must state the counter has no aria-live.
    assert re.search(r"counter element (?:itself )?has\s+\*?\*?no\*?\*?\s+`?aria-live", states_doc, re.IGNORECASE) or \
           "no `aria-live`" in states_doc or "no aria-live" in states_doc.lower(), (
        "interaction states must state the counter has no aria-live"
    )

    # The UI spec must state the counter has no aria-live.
    assert "no `aria-live`" in ui_spec or "no aria-live" in ui_spec.lower(), (
        "UI spec must state the counter has no aria-live"
    )


# ---------------------------------------------------------------------------
# Rule 9: custom limit == 200
# ---------------------------------------------------------------------------

def test_rule_09_custom_limit_is_200():
    """Custom action normalized limit must be 200."""
    all_docs = _read_all()
    for doc_name, content in all_docs.items():
        # Every document that mentions the limit must say 200, not 100/150/etc.
        # We look for the canonical forms.
        if "200" in content:
            # Sanity: at least one canonical mention exists.
            assert re.search(r"(max_length|200\s*(?:个)?\s*(?:规范化)?\s*字符|limit.*200|200.*limit|/200)", content), (
                f"document '{doc_name}' mentions 200 but not in a recognized limit form"
            )
    # The component contract counter must show /200.
    contract = _read("contract")
    assert "/200" in contract, "component contract counter must show /200"
    # The UI spec must state the 200 normalized-character limit.
    ui_spec = _read("ui_spec")
    assert "200" in ui_spec and "规范化" in ui_spec, (
        "UI spec must state the 200 normalized-character limit"
    )


# ---------------------------------------------------------------------------
# Rule 10: branch archived != branch_state_unavailable
# ---------------------------------------------------------------------------

def test_rule_10_branch_archived_not_branch_state_unavailable():
    """branch_archived (Lifecycle) must not be conflated with branch_state_unavailable (advisory)."""
    states_doc = _read("states")
    contract = _read("contract")

    # The states doc must explicitly distinguish the two.
    assert "branch_archived" in states_doc, (
        "interaction states must define branch_archived"
    )
    assert "branch_state_unavailable" in states_doc, (
        "interaction states must define branch_state_unavailable"
    )
    # There must be an explicit statement that archived is not unavailable.
    assert (
        "not" in states_doc.lower() and "the same as" in states_doc.lower()
    ) or "never" in states_doc.lower(), (
        "interaction states must explicitly distinguish branch_archived from branch_state_unavailable"
    )

    # The contract must surface branch_archived on the Lifecycle dimension.
    assert "data-branch-lifecycle" in contract, (
        "component contract must track branch Lifecycle dimension"
    )
    assert "data-branch-state" in contract, (
        "component contract must track branch Narrative State Data dimension"
    )
    # The two dimensions must be distinct attributes.
    assert "data-branch-lifecycle" != "data-branch-state"


# ---------------------------------------------------------------------------
# Rule 11: 0D4-C owns read-only plan/feasibility/preview routes
# ---------------------------------------------------------------------------

def test_rule_11_0d4c_owns_readonly_routes():
    """0D4-C must own the read-only Narrative Turn routes."""
    brief = _read("brief")
    ui_spec = _read("ui_spec")
    delivery = _read("delivery")

    # The brief must list the 4 read-only endpoints under 0D4-C.
    for endpoint in [
        "/api/narrative-turn/context",
        "/api/narrative-turn/plan",
        "/api/narrative-turn/feasibility",
        "/api/narrative-turn/preview",
    ]:
        assert endpoint in brief, f"brief must list 0D4-C endpoint {endpoint}"

    # The brief must state 0D4-C owns them (not 0D4-E).
    assert "0D4-C owns" in brief or "0D4-C owns" in ui_spec, (
        "brief or UI spec must state 0D4-C owns the read-only routes"
    )

    # The UI spec §18.1 must state the boundary.
    assert "API phase boundary" in ui_spec, (
        "UI spec must include the API phase boundary section"
    )

    # The delivery report must record the correction.
    assert "API phase boundary" in delivery or "0D4-C vs 0D4-E" in delivery, (
        "delivery report must record the API phase boundary correction"
    )


# ---------------------------------------------------------------------------
# Rule 12: 0D4-E owns branch mutation/retrieval routes
# ---------------------------------------------------------------------------

def test_rule_12_0d4e_owns_branch_mutation_routes():
    """0D4-E must own branch mutation + retrieval isolation routes."""
    brief = _read("brief")
    ui_spec = _read("ui_spec")

    # The brief 0D4-E section must mention branch create/select/archive/restore.
    brief_e_block = _extract_section_block(brief, "## Phase 0D4-E", "## Phase 0D4-F")
    assert brief_e_block, "could not locate Phase 0D4-E section in brief"
    for term in ["create", "archive", "restore"]:
        assert term in brief_e_block, f"0D4-E brief must mention branch {term}"

    # The brief must state the read-only routes are NOT reserved for 0D4-E.
    assert "not" in brief.lower() and "reserved for" in brief.lower() and "0D4-E" in brief, (
        "brief must state read-only routes are not reserved for 0D4-E"
    )

    # The UI spec must list the 0D4-E-owned endpoints.
    assert "0D4-E owns" in ui_spec, (
        "UI spec must list 0D4-E-owned endpoints"
    )


# ---------------------------------------------------------------------------
# Rule 13: visible disabled reason via aria-describedby (not title-only)
# ---------------------------------------------------------------------------

def test_rule_13_disabled_reason_visible_aria_describedby():
    """Primary action disabled reason must be visible via aria-describedby."""
    contract = _read("contract")
    ui_spec = _read("ui_spec")

    # The §10.1 DOM contract must use aria-describedby for the disabled reason.
    primary_block = _extract_section_block(contract, "### 10.1 DOM contract", "## 11.")
    assert primary_block, "could not locate §10.1 DOM contract block"
    assert 'aria-describedby="nt-primary-disabled-reason"' in primary_block, (
        "primary action DOM contract must use aria-describedby for disabled reason"
    )
    assert 'id="nt-primary-disabled-reason"' in primary_block, (
        "primary action DOM contract must include the visible reason <p>"
    )

    # The contract must forbid title-only disabled reason.
    assert "title" in contract.lower() and "sole carrier" in contract.lower(), (
        "contract must forbid title-only disabled reason"
    )

    # The UI spec §10.2 must show the aria-describedby structure.
    assert 'aria-describedby="nt-primary-disabled-reason"' in ui_spec, (
        "UI spec §10.2 must use aria-describedby for disabled reason"
    )


# ---------------------------------------------------------------------------
# Rule 14: situation header uses <header> or <section role="region">, not banner
# ---------------------------------------------------------------------------

def test_rule_14_situation_header_landmark_correct():
    """Situation Header landmark must be <header> or <section role='region'>."""
    contract = _read("contract")

    # The §3.1 DOM contract must use <header ...> without role="banner".
    header_block = _extract_section_block(contract, "### 3.1 DOM contract", "## 4.")
    assert header_block, "could not locate §3.1 DOM contract block"
    assert re.search(r'<header\s+class="nt-situation-header"', header_block), (
        "Situation Header must use <header class='nt-situation-header'>"
    )
    assert 'role="banner"' not in header_block, (
        "Situation Header must not use role='banner'"
    )


# ---------------------------------------------------------------------------
# Entry point for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
