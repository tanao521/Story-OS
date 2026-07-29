# Phase 0D5-C-RC1 Delivery Report

## Verdict

**PARTIALLY PASSED — FIX REQUIRED**. Real browser interaction evidence is now recorded for entry, branch lifecycle, URL/history behavior, and console cleanliness. The final three-Turn durable progression gate remains open because the isolated fixture has no ready Canon/source/vector authority.

## Browser evidence

| Scenario | Result | Evidence |
|---|---|---|
| Default simulator entry | PASS | Shell visible; scope bar rendered |
| Missing branch | PASS | `BRANCH_SETUP`; URL unchanged; no auto-select |
| Create inactive branch | PASS | B2 row appeared; active remained root |
| Browse | PASS | URL changed to `view=history`; active pointer unchanged |
| Select | PASS | one explicit select; URL and active row became alternate |
| Archive replacement | PASS | alternate archived; active became b2 |
| Restore | PASS | alternate reopened open/inactive; active remained b2 |
| Back/Forward | PASS | Browse B2 → Browse alternate → back → forward restored URLs |
| Fresh-tab console | PASS | 0 error/warn entries after load and interactions |
| Three durable Turns | BLOCKED | fixture reports missing Canon/source/vector readiness |

Browser engine: Codex In-app Browser, Chromium-backed, exact version unavailable; background/headless. Fixture address: `127.0.0.1:7862`. Temporary fixture root: `%TEMP%/rc2_browser_ws_pq6i5qyh`. Start/stop: started successfully; stopped after evidence collection.

## Production fixes made from browser symptoms

1. `simulator-panel-review.css`: excluded the new loop shell from the legacy simulator hide rule. Symptom: shell had `display:none` in a real browser.
2. `simulator-usable-loop.js`: replaced unsupported `window.prompt/confirm` with keyboard-accessible dialog controls. Symptom: in-app Chromium reported `prompt() is not supported`.
3. `simulator-usable-loop.js`: missing branch now remains `BRANCH_SETUP`; no implicit active-branch URL mutation. Symptom: normal `mode=simulator` silently selected root.
4. `simulator-usable-loop.js`: explicit Select synchronizes the URL to the selected branch after the existing lifecycle mutation.

## Commands

- `python -m pytest tests/test_phase0d5c_*.py -q`: 11 passed, 0 failed, exit 0.
- `python tests/_phase0d5c_browser_acceptance.py`: Total 4, PASS 4, FAIL 0, SKIP 0, exit 0.
- `node --check web/static/simulator-usable-loop.js`: exit 0.
- `node --check web/static/simulator-narrative-turn.js`: exit 0.
- Limited prior regression: 172 passed, 0 failed, exit 0.
- `python tests/_phase0d5c_real_browser_acceptance.py`: fixture probe only; not counted as browser evidence.

Category labels overlap and are not additive. Provider calls: 0. External network: 0. Approval mutations: 0. Commit mutations: 0. Canon writes: 0. Chroma writes: 0. Real project writes: 0. Git writes: 0.
