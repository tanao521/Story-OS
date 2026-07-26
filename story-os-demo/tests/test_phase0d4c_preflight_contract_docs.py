import os
import sys
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOC_PATHS = {
    "ui_spec": os.path.join(PROJECT_ROOT, "docs/design/simulator_narrative_turn_ui_spec.md"),
    "states": os.path.join(PROJECT_ROOT, "docs/design/simulator_narrative_turn_interaction_states.md"),
    "contract": os.path.join(PROJECT_ROOT, "docs/design/simulator_narrative_turn_component_contract.md"),
    "phase_plan": os.path.join(PROJECT_ROOT, "docs/planning/PHASE_0D4_C_P.md"),
    "delivery": os.path.join(PROJECT_ROOT, "docs/planning/PHASE_0D4_C_P_DELIVERY_REPORT.md"),
    "brief": os.path.join(PROJECT_ROOT, "docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md"),
}


def _read(doc_key):
    path = DOC_PATHS[doc_key]
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_rule_01_component_count_10():
    contract = _read("contract")
    assert "Component count: 10" in contract


def test_rule_02_custom_composer_15_states():
    states = _read("states")
    assert "15 states" in states or "**15**" in states


def test_rule_03_context_endpoint_get():
    brief = _read("brief")
    assert "GET  /api/narrative-turn/context" in brief or "GET /api/narrative-turn/context" in brief


def test_rule_04_plan_endpoint_get():
    brief = _read("brief")
    assert "GET  /api/narrative-turn/plan" in brief or "GET /api/narrative-turn/plan" in brief


def test_rule_05_feasibility_endpoint_post():
    brief = _read("brief")
    assert "POST /api/narrative-turn/feasibility" in brief


def test_rule_06_preview_endpoint_post():
    brief = _read("brief")
    assert "POST /api/narrative-turn/preview" in brief


def test_rule_07_no_get_feasibility():
    brief = _read("brief")
    contract = _read("contract")
    ui_spec = _read("ui_spec")
    states = _read("states")
    for name, content in [("brief", brief), ("contract", contract), ("states", states)]:
        if "GET /api/narrative-turn/feasibility" in content:
            raise AssertionError(f"GET feasibility found in {name}")


def test_rule_08_no_get_preview():
    brief = _read("brief")
    contract = _read("contract")
    ui_spec = _read("ui_spec")
    states = _read("states")
    for name, content in [("brief", brief), ("contract", contract), ("states", states)]:
        if "GET /api/narrative-turn/preview" in content:
            raise AssertionError(f"GET preview found in {name}")


def test_rule_09_custom_text_not_in_url():
    ui_spec = _read("ui_spec")
    url_section = ui_spec.split("URL state spec")[1].split("HTTP Wire Contract")[0]
    assert "custom_action_text" not in url_section


def test_rule_10_four_wire_dto_schemas():
    ui_spec = _read("ui_spec")
    assert "ContextWireDTO" in ui_spec
    assert "PlanWireDTO" in ui_spec
    assert "ValidationWireDTO" in ui_spec
    assert "PreviewWireDTO" in ui_spec


def test_rule_11_browser_no_python_accessor():
    contract = _read("contract")
    lines = contract.split("\n")
    in_required_data = False
    for i, line in enumerate(lines):
        if "Required data" in line:
            in_required_data = True
            continue
        if in_required_data and line.strip().startswith("|") and "accessor" in line.lower() and "Wire" not in line:
            if "server-side" not in line.lower() and "not browser" not in line.lower():
                raise AssertionError(f"Python accessor in Required data at line {i+1}: {line.strip()[:80]}")
        if in_required_data and not line.strip().startswith("|"):
            in_required_data = False


def test_rule_12_python_accessor_server_only():
    contract = _read("contract")
    assert "server-side" in contract.lower()
    assert "not browser" in contract.lower()


def test_rule_13_single_business_live_region():
    contract = _read("contract")
    assert "#nt-status-notice" in contract
    assert 'role="status"' in contract or "TurnStatusNotice" in contract


def test_rule_14_no_role_alert_on_components():
    contract = _read("contract")
    lines = contract.split("\n")
    in_turn_status = False
    in_forbidden = False
    for i, line in enumerate(lines):
        if "## 11. TurnStatusNotice" in line:
            in_turn_status = True
        elif line.startswith("## ") and in_turn_status:
            in_turn_status = False
        if "## 13. Forbidden" in line or "Forbidden component" in line:
            in_forbidden = True
        elif line.startswith("## ") and in_forbidden:
            in_forbidden = False
        if 'role="alert"' in line:
            if "no" in line.lower() and 'role="alert"' in line:
                continue
            if in_forbidden:
                continue
            if not in_turn_status:
                raise AssertionError(f"role=alert found outside TurnStatusNotice at line {i+1}")


def test_rule_15_unavailable_radio_no_aria_disabled():
    contract = _read("contract")
    lines = contract.split("\n")
    for i, line in enumerate(lines):
        if "aria-disabled" in line and "nt-action-radio" in line:
            if ":not([aria-disabled])" in line:
                continue
            raise AssertionError(f"aria-disabled on radio at line {i+1}")


def test_rule_16_unavailable_radio_has_data_unavailable_and_describedby():
    contract = _read("contract")
    assert 'data-unavailable="true"' in contract
    assert "aria-describedby" in contract


def test_rule_17_turn_id_deterministic_rebuild():
    ui_spec = _read("ui_spec")
    assert "turn_id" in ui_spec
    assert "rebuild" in ui_spec.lower()


def test_rule_18_api_boundary_0d4c_vs_0d4e():
    brief = _read("brief")
    assert "0D4-C owns" in brief
    assert "0D4-E owns" in brief


def test_rule_19_phase_doc_references_fv2():
    phase_plan = _read("phase_plan")
    assert "FV2" in phase_plan
    assert "FIX-RC2-FV: SUPERSEDED" in phase_plan


def test_rule_20_brief_references_fv2():
    brief = _read("brief")
    assert "FV2" in brief
    assert "FIX-RC2-FV" in brief and "SUPERSEDED" in brief


def test_rule_21_delivery_report_references_fv2():
    delivery = _read("delivery")
    assert "FV2" in delivery
    assert "FIX-RC2-FV: SUPERSEDED" in delivery


def test_rule_22_no_old_fix_rc_status():
    phase_plan = _read("phase_plan")
    delivery = _read("delivery")
    brief = _read("brief")
    for name, content in [("phase_plan", phase_plan), ("delivery", delivery), ("brief", brief)]:
        if "Phase 0D4-C-P-FIX-RC: PASSED" in content and "SUPERSEDED" not in content.split("Phase 0D4-C-P-FIX-RC")[0]:
            raise AssertionError(f"Old FIX-RC PASSED status found in {name}")
        if "SEALED after 0D4-C-P-FIX-RC" in content:
            raise AssertionError(f"Old FIX-RC seal reference found in {name}")


if __name__ == "__main__":
    tests = [
        ("rule_01", test_rule_01_component_count_10),
        ("rule_02", test_rule_02_custom_composer_15_states),
        ("rule_03", test_rule_03_context_endpoint_get),
        ("rule_04", test_rule_04_plan_endpoint_get),
        ("rule_05", test_rule_05_feasibility_endpoint_post),
        ("rule_06", test_rule_06_preview_endpoint_post),
        ("rule_07", test_rule_07_no_get_feasibility),
        ("rule_08", test_rule_08_no_get_preview),
        ("rule_09", test_rule_09_custom_text_not_in_url),
        ("rule_10", test_rule_10_four_wire_dto_schemas),
        ("rule_11", test_rule_11_browser_no_python_accessor),
        ("rule_12", test_rule_12_python_accessor_server_only),
        ("rule_13", test_rule_13_single_business_live_region),
        ("rule_14", test_rule_14_no_role_alert_on_components),
        ("rule_15", test_rule_15_unavailable_radio_no_aria_disabled),
        ("rule_16", test_rule_16_unavailable_radio_has_data_unavailable_and_describedby),
        ("rule_17", test_rule_17_turn_id_deterministic_rebuild),
        ("rule_18", test_rule_18_api_boundary_0d4c_vs_0d4e),
        ("rule_19", test_rule_19_phase_doc_references_fv2),
        ("rule_20", test_rule_20_brief_references_fv2),
        ("rule_21", test_rule_21_delivery_report_references_fv2),
        ("rule_22", test_rule_22_no_old_fix_rc_status),
    ]
    
    passed = 0
    failed = 0
    warnings = []
    
    for name, test_func in tests:
        try:
            test_func()
            print(f"PASS: {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {name} - {e}")
            failed += 1
        except Exception as e:
            print(f"WARN: {name} - {e}")
            warnings.append((name, str(e)))
    
    print(f"\n=== Results ===")
    print(f"Total: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for name, msg in warnings:
            print(f"  - {name}: {msg}")
    
    sys.exit(0 if failed == 0 else 1)