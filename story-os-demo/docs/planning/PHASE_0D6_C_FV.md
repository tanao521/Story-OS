# Phase 0D6-C-FV — Browser, Recovery & Accessibility Final Verification

> **Final status update — 2026-07-30: Phase 0D6-C — SEALED.**
>
> The historical FV hold and RC requirements recorded below were closed by
> RC13–RC19 and the authorized FV2 independent verification. The authoritative
> final ledger is `PHASE_0D6_C_SEAL.md`: 2399 passed, 0 failed, 0 skipped;
> symlink security 7/7; and the frozen Chromium matrix 20/20 remains valid
> with no production drift after its baseline.
>
> RC1 status update: the successor-as-previous readiness defect is corrected in Phase 0D6-C-B-RC1. FV remains unsealed until the authorized FV2 browser matrix is completed.
>
> RC10 status update: versioned n-gram namespace, metadata validation, cold
> reopen, clean-room vector authority, and formal completion passed. FV2
> remains unauthorized because ProjectManager registry UUIDs and narrative
> Branch/Simulator slug identities cannot yet form the required same-service
> multi-project browser fixture.

> RC11 update: Branch/Simulator now have a registry-authoritative UUID/storage
> compatibility path and the formal fixture is constructible. Chromium exposed
> the remaining Narrative Turn/chapter-progression caller mismatch. RC12 is
> required; FV2 remains unauthorized.

> RC12 update: Narrative Turn and chapter progression now preserve canonical
> UUID scope across browser/API/DTO/operation boundaries while using the
> registered slug only for legacy storage. A sibling-branch delayed GET can
> still render the prior branch's held READY response. RC13 is required and
> FV2 remains unauthorized.

## Purpose

This phase is the final browser-level verification of the sealed 0D6-B authority and the 0D6-C-P/A/B Simulator surface. It verifies that one explicit start action, durable replay, navigation recovery, Traditional isolation, and accessible controls agree with the frozen contracts. This phase does not alter production behavior.

## Authority Baseline

- 0D6-A is PASSED and SEALED.
- 0D6-B is PASSED and SEALED.
- 0D6-C-P is PASSED.
- 0D6-C-A is PASSED.
- 0D6-C-B is PASSED — READY FOR C-FV.
- The browser may call only the existing progression readiness GET and durable start POST. It may not create chapters, plans, transitions, files, branches, commits, Canon, Chroma, Obsidian, provider, or external records.

## Browser Environment

Verification used the in-app Chromium Browser against an isolated FastAPI/uvicorn fixture on `http://127.0.0.1:7863`. The fixture seeds a committed chapter 1, an authoritative successor chapter 2, and the narrative-turn context inputs under a temporary workspace. `tests/_phase0d6c_fv_browser_fixture_server.py` audits only the two progression endpoints and can deterministically drop one successful start response.

## Basic Start Flow

The initial Simulator page rendered `READY`, exposed one enabled `Start next chapter` button, and displayed the no-auto-confirm warning. One explicit click produced a single HTTP 200 durable start response with the expected scope, successor chapter, operation ID, and `turn_status=awaiting_action`. The browser URL was rebound to the returned successor chapter and Turn ID, and the Narrative Turn workspace loaded.

The final acceptance condition was not met: after rebind, the progression panel performed a fresh readiness read using `chapter_id=2` as `previous_chapter_id` and rendered `BLOCKED — Previous chapter is not complete`. The successor workspace itself was visible, but the same page did not converge to the expected `AWAITING_ACTION` progression presentation. This is a production-code defect surfaced by FV and is retained for RC; no production fix is made in FV.

## Double-Click Verification

Two immediate activations of the ready control produced exactly one start POST. The request carried one operation ID and one frozen readiness fingerprint. The browser reached the same successor URL as the single-click flow.

## Response-Loss Replay

With `STORYOS_FV_DROP_START_RESPONSE=1`, the fixture durably completed the first start and dropped its response body. The browser rendered `START_RETRYABLE_ERROR` / `Start result is unconfirmed`. Retry emitted a second POST with byte-for-byte identical operation scope and operation ID. The durable service replayed the existing result and the browser rebound to the same Turn. The post-rebind panel defect remained.

## Safe Error Verification

The response-loss path was classified as ambiguous and retryable. No alternate operation ID, speculative client repair, or automatic action confirmation was observed. The safe error path is therefore PASS for the exercised response-loss condition.

## Context Race

The browser contract tests cover epoch/context invalidation and stale-response handling. A real delayed-response race was not promoted to acceptance after the basic-flow defect was observed; it remains `SKIPPED — blocked by the basic-flow defect` for this FV run.

## Reload

Reloading the successor URL preserved the returned Turn URL and Narrative Turn workspace. The progression panel still reproduced the same blocked successor-readiness state, so reload recovery is recorded as partial.

## Back/Forward

Back returned to the original chapter scope and exposed the authoritative existing-Turn continuation state without issuing a duplicate start. Forward returned to the successor Turn URL and workspace. The blocked panel remained after forward.

## Existing Turn

The back-navigation state exposed the existing durable Turn continuation path. No new POST was required for that state. Full post-fix visual acceptance is deferred with the RC.

## Traditional Isolation

Traditional mode rendered without the progression region and generated no progression audit file or readiness/start request. This is PASS.

## Filesystem Allowlist

FV may add/update only this plan, its delivery report, and browser test/helper evidence. Production files remain untouched. The isolated fixture writes only below the temporary workspace; no project repository data is used.

## Mobile Viewports

No viewport-specific acceptance is claimed because the basic successor rebind gate failed. Mobile layout and 44px target smoke are `SKIPPED — blocked by the basic-flow defect`.

## Accessibility

The ready control exposes an accessible role/name and `aria-describedby="simulator-chapter-progression-status"`; the status text is present in the DOM. Keyboard and focus contract assertions remain covered by the existing C-B tests. Full post-rebind focus acceptance is `SKIPPED — blocked by the basic-flow defect`.

## Network Boundary

The browser audit observed only readiness GET and start-turn POST calls. Traditional mode observed zero progression calls. The response-loss retry reused the same frozen request. No browser-side filesystem, provider, or external network write was observed.

## Regression Matrix

| Area | Result |
| --- | --- |
| Targeted C-A/C-B frontend and authority tests | PASS |
| Associated 0D4/0D5 narrative, Traditional, static-path tests | PASS |
| Node syntax checks | PASS |
| Basic browser start → AWAITING_ACTION convergence | FAIL — RC REQUIRED |
| Double-click single-flight | PASS |
| Response-loss safe retry | PASS |
| Reload/back/forward | PARTIAL — successor panel remains blocked |
| Traditional isolation | PASS |
| Mobile/accessibility final smoke | SKIPPED — blocked by basic-flow defect |

## Browser Limitation Policy

If Chromium is unavailable, the result must be `PARTIALLY PASSED — BROWSER VERIFICATION INCOMPLETE`; no browser pass may be claimed. Chromium was available for this run. Because Chromium exposed a production defect, the result is `PARTIALLY PASSED — RC REQUIRED`.

## Seal Gate

0D6-C-FV is not sealed. The minimum RC must make a validated durable-start success render the returned successor Turn as `AWAITING_ACTION` without re-reading the successor as a new previous-chapter progression scope, then repeat the browser matrix including mobile and focus smoke.

## Non-Goals

No production fix, backend authority change, lifecycle redesign, provider integration, non-main timeline support, 0D6-D, 0D7, or 0E work is included.
