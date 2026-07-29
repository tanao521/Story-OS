# Phase 0D5-C — Simulator Branch Controls, Multi-Turn Continuation & Turn History

状态：**PARTIALLY PASSED — FIX REQUIRED**

## Scope

0D5-C adds the product read shell around the existing `SimulatorLoopStateService` and existing narrative-turn/branch lifecycle APIs. It does not add a compiler, commit entry point, approval mutation, chapter completion mutation, or a second authority.

## Delivered behavior

- `GET /api/simulator/state` drives the simulator shell: authority context, chapter progress, branch readiness/evidence, recovery, current result, and immutable Turn History.
- Entry resolves the authoritative active branch by reading the branch registry; it never creates or selects a branch implicitly.
- Browse is URL-only. Select, create, archive-with-replacement, and restore call existing branch lifecycle routes. Create and restore leave the branch inactive.
- Continue to next Turn clears turn/action URL parameters and uses the existing narrative-turn module. Confirm publishes a read-model refresh event.
- Recovery states are displayed read-only and mutation controls are disabled while blocked or stale.
- URL refresh, popstate, and back/forward reload authoritative state. Traditional Mode remains on existing routes.
- CSS reuses Story OS tokens and includes responsive/reduced-motion rules; stable `data-*` selectors support browser acceptance and accessibility.

## Safety

Provider calls: 0. External network: 0. Canon writes: 0. Chroma writes: 0. Commit bypass: 0. Git writes: 0. No localStorage or frontend authority was introduced.

## Gate

The isolated harness proves page/route/state/Traditional Mode checks, but it does not yet provide real-browser evidence for three confirmed Turns plus refresh/back-forward/recovery. Therefore 0D5-C is not sealed and 0D5-D is not entered.

RC1 browser evidence is recorded in `PHASE_0D5_C_RC1.md` and `PHASE_0D5_C_RC1_DELIVERY_REPORT.md`. Entry, branch lifecycle, and history interactions pass; the three durable-Turn gate remains blocked by fixture authority readiness.

RC2 added the authoritative ready fixture and verified two durable Turns plus a server-derived Turn 3. Response-loss is fail-closed, but durable-result-before-response-loss recovery remains open; 0D5-C is therefore still unsealed.

RC3 closes the exact durable-completion-before-response-loss scenario with a fixture-only transport fault. The same durable result is recovered without a second Confirm, so 0D5-C is sealed.
