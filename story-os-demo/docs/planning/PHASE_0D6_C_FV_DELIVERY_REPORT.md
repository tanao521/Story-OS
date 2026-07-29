# Phase 0D6-C-FV Delivery Report

## Outcome

**PARTIALLY PASSED — RC REQUIRED.** Chromium was available and exercised against an isolated real FastAPI application. Explicit start, single-flight, response-loss replay, navigation recovery, and Traditional isolation produced the expected network boundaries. The basic acceptance gate failed after the successful successor rebind: the progression panel re-read `chapter_id=2` as `previous_chapter_id=2` and displayed `BLOCKED — Previous chapter is not complete` while the successor Narrative Turn workspace was visible.

This report intentionally does not modify production code. The observed defect is retained as the minimum RC scope.

## Changed Files

- Added `tests/_phase0d6c_fv_browser_fixture_server.py` — isolated browser fixture, request audit, and deterministic response-loss injector.
- Added `docs/planning/PHASE_0D6_C_FV.md` — FV protocol and seal gate.
- Added this delivery report.
- Production files changed by FV: **0**.

## Browser Environment

- In-app Chromium Browser.
- Local server: `127.0.0.1:7863`.
- Temporary fixture project: `0d6c-fv-project`.
- Real routes exercised: `GET /api/chapter-progression/readiness`, `POST /api/chapter-progression/start-turn`.

## Basic Flow Evidence

1. Initial URL rendered one enabled `Start next chapter` control and `READY` status.
2. Explicit click emitted one POST with `previous_chapter_id=1`, `successor_chapter_id=2`, one operation ID, and a 64-hex readiness fingerprint; response status was 200.
3. The URL rebound to `chapter_id=2&turn_id=turn_04924aa15013b4f4` and the Narrative Turn workspace loaded.
4. The progression region then rendered `Previous chapter is not complete` / `BLOCKED` with scope `Previous chapter 2`.

This violates the C-B contract that a validated success rebinds to the returned initial Turn and renders it in `AWAITING_ACTION`. The likely defect is the progression module continuing to derive `previous_chapter_id` from the rebound successor URL. The exact production correction is deferred to RC.

## Double-Click Evidence

On a fresh fixture, `clickCount=2` produced exactly one audited POST (operation `c7f5e89c-0c82-44af-9776-d03efab5ebf6`) and one successor URL. No duplicate operation was observed.

## Response-Loss Replay Evidence

With the first successful start response intentionally dropped, operation `19e91219-1c14-4f17-9bfe-396744aed26b` produced:

- POST 1: status 200, `dropped=true`.
- POST 2: status 200, `dropped=false`.
- Both bodies had the same operation ID, scope, successor, and readiness fingerprint.

The browser first showed `Start result is unconfirmed`, then safely retried and rebound to the same Turn. No automatic action confirmation occurred.

## Error Mapping Evidence

The ambiguous empty response was mapped to `START_RETRYABLE_ERROR` with a visible safe-retry control. No speculative repair or new operation was generated.

## Context Race Evidence

Static C-B coverage exists for epoch/context races. A real delayed-response browser race was not accepted after the basic-flow defect and is recorded as skipped for this run.

## Reload Evidence

Reload preserved the successor Turn URL and loaded the Narrative Turn workspace. The blocked progression panel reproduced, so recovery is partial pending RC.

## Back/Forward Evidence

Back returned to chapter 1 and exposed the existing durable Turn continuation state without a duplicate POST. Forward returned to the successor Turn URL/workspace. The blocked panel reproduced on the successor page.

## Existing-Turn Evidence

The back-navigation state exposed the existing-Turn continuation affordance. No start POST was required for that state. Full acceptance is deferred until the successor rebind defect is corrected.

## Traditional Isolation Evidence

Fresh Traditional navigation rendered without a progression region. The fixture did not create `.fv_network_audit.json`, proving zero readiness/start calls in Traditional mode.

## Filesystem Diff

FV writes were confined to the new helper and two planning documents. Temporary fixture data and audit JSON were outside the repository. No production source file was written by the FV run. Pre-existing dirty-worktree changes were preserved and not attributed to FV.

## Mobile Evidence

`SKIPPED — blocked by the basic-flow defect`; no mobile pass is claimed.

## Accessibility Evidence

The ready button had an accessible role/name and `aria-describedby="simulator-chapter-progression-status"`; status text was present. Existing C-B tests cover keyboard wiring and focus semantics. Successor focus acceptance is skipped because the successor panel did not converge.

## Network/Safety Evidence

Browser calls were limited to the two progression routes. Double-click remained single-flight. Response-loss retry reused the frozen request. Traditional mode issued zero progression requests. No browser filesystem/provider/external write was observed.

## Targeted Regression Ledger

| Command | Result |
| --- | --- |
| `python -m pytest -q tests/test_phase0d6c_a_frontend.py tests/test_phase0d6c_b_frontend.py tests/test_phase0d6b_authority.py tests/test_phase0d6b_fv1.py tests/test_phase0d6b_fv2.py tests/test_phase0d4c_narrative_turn_frontend_contract.py tests/test_phase0d4c_narrative_turn_routes.py tests/test_phase0d4d_frontend_contract.py tests/test_phase0d4d_confirm_routes.py tests/test_phase0d5c_frontend_contract.py tests/test_phase0d5d1_traditional_isolation.py tests/test_phase0d5d2_frontend_contract.py tests/test_static_path_guard.py` | **225 passed, 0 failed, 0 skipped** |
| `node --check web/static/simulator-chapter-progression.js` | PASS |
| `node --check web/static/simulator-context-navigator.js` | PASS |
| `node --check web/static/simulator-narrative-turn.js` | PASS |
| `git diff --check` | PASS; only pre-existing LF/CRLF warnings |

## Production-Code Diff Check

No production code was changed by this FV. The helper is test-only and the remaining changes are planning/report documents. No commit, branch switch, push, dependency, CI, database, or remote-resource action was performed.

## Remaining Limitations

The successor rebind must stop the progression panel from treating the successor chapter as a new previous-chapter start scope, while preserving the returned Turn ID and `AWAITING_ACTION` state. After that RC, repeat real browser checks for delayed context races, mobile widths, keyboard activation/focus after rebind, and the complete reload/back/forward matrix.

## Seal Recommendation

Do **not** seal 0D6-C-FV. Open a focused RC for the successor rebind/readiness ownership defect, then rerun this FV matrix. No later phase is recommended until the RC passes and C-FV is sealed.
