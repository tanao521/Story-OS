# Phase 0D8-FV-RC4 Delivery Report

Date: 2026-08-01

## Scope and result

RC4 repaired only the Gate 3 browser projection and delayed-commit attribution defect. RC1 selection convergence, RC2 integrity guards, RC3 fingerprint guards, Commit authority, revision lineage, and downstream providers were left unchanged.

Result: **PASS - ready to resume the remaining Phase 0D8-FV gates only with separate owner authorization.** Gate 4 duplicate replay was not executed and Phase 0D8-SEAL was not entered.

## Root cause and repair

The legacy chapter-level `review-status` projection could continue to show an unlabeled `approved` state while the selected version had moved to Z. The approval UI also reported completion without naming the frozen source version.

The minimal production repair is limited to `web/static/app.js` and the `app.js?v=13` cache buster in `web/templates/index.html`. Exact-version state now owns the visible review status for the active selection; selection clears and reloads that projection; and the approval/commit operation captures its source identity before the request and reports the trusted committed source version. No backend authority path was redesigned.

## Gate 3 browser evidence

Evidence: `.tmp/phase0d8fv-rc4-projection/gate3-delayed-commit.json`.

The harness held the response after the server had durably completed Y, selected Z while that response was held, then released it. Both the held-response and post-release views showed selected/review/preview `manual_v007` (Z), visible exact review status `STALE`, and exact transition `STALE`. No approval or Commit POST occurred after Z selection except the authorized version selection request. The visible notification was `提交完成：manual_v006（第 1 章）` (Y).

Durable authority remained exactly Y: one CommitRun, one Canon revision, source `manual_v006`, matching source fingerprint and decision ID, and equal approval provenance. The operation ID was read from the durable server CommitRun rather than fabricated by the browser harness.

The normal current-Y control is `.tmp/phase0d8fv-rc4-projection/normal-current-y.json`; it produced one Y CommitRun/Canon result and a Y-attributed completion log. The delayed scenario also serves as the projection-only control because Z selection generated no approval or Commit mutation.

## Validation

- RC4 focused regression: **57 passed**.
- RC4 expanded review/route/Commit/version/frontend regression: **137 passed**.
- Full suite: **2488 passed, 0 failed, 0 skipped**; two pre-existing `PytestUnknownMarkWarning` warnings.
- `node --check web/static/app.js`: passed.
- Python compilation for the Gate runners, fixture, and RC4 tests: passed.
- `git diff --check`: passed.
- Disk SHA-256 for `web/static/app.js`: `DA9F4E93568D0B2D31CD4A5A89DD2E2F57A80B81C8140CAA72CF50C81ECD550A`.
- Fresh Edge execution loaded `app.js?v=13`; harness fixture, temporary profiles, and ports 7867/7868 were cleaned. Existing user Edge processes were not touched.

## Test-only additions and remaining boundary

`tests/test_phase0d8fv_rc4_projection.py` adds four deterministic static regressions for exact projection ownership, reload/clear behavior, frozen notification identity, and asset cache-busting.

Gate 4 duplicate replay remains **NOT EXECUTED** under the RC4 authorization. RC4 permits resuming it, but this report does not authorize that action. No commit, push, PR, SEAL, or remote mutation was performed.

## SEAL reconciliation (current state)

RC4 current result: **PASSED**. The Gate 4-not-executed language above is the
historical RC4 checkpoint; Gate 4 subsequently passed under separate
authorization, and Phase 0D8 is now sealed.
