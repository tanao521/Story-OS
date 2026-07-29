# Phase 0D5 Implementation Brief

Current gate: **0D5-P/A/B PASSED · 0D5-C/D SEALED · 0D5-RC PASSED · 0D5 SEALED**.

## Objective

Turn the existing branch-aware simulator foundations into a discoverable, recoverable, multi-Turn product loop without creating a second Canon, commit path, or provider path.

## Non-negotiable boundaries

Use the existing narrative-turn, branch lifecycle, Narrative Chapter Compiler, Candidate Version, and ChapterCommitService contracts. Keep Traditional Writing Mode on its existing routes and services. Production live remains default-off until RC evidence is complete.

## Product contract to implement later

1. Enter simulator with explicit project, timeline, branch, chapter, and source scope.
2. Confirm a Turn and visibly load the next Turn while appending immutable Turn History.
3. Switch/create/archive/restore branches with lifecycle and readiness shown.
4. Compile a Candidate, inspect it, review/approve it, then commit exactly once through ChapterCommitService.
5. Show chapter progression and recover the same operation/Turn state after refresh or replay.
6. Keep traditional generation, editing, revisions, quality review, version selection, and Canon paths unchanged.

## Delivery sequence

See the split in `PHASE_0D5_P_DELIVERY_REPORT.md`: design (A), read/status aggregation (B), branch and multi-Turn UX (C), compile/review/commit UX (D), and isolated browser RC.

0D5-A design closure is in `docs/design/simulator_usable_loop_ui_spec.md`, `simulator_usable_loop_interaction_states.md`, `simulator_usable_loop_component_contract.md`, `simulator_usable_loop_accessibility_contract.md`, and `simulator_usable_loop_backend_gap_contract.md`. No production implementation was entered.

0D5-B read-model closure is in `PHASE_0D5_B.md` and `PHASE_0D5_B_DELIVERY_REPORT.md`. The only new product route is the read-only `GET /api/simulator/state`; Candidate approval remains an explicit backend gap and 0D5-C is not entered.

## Acceptance evidence used for sealing

An isolated browser fixture demonstrated two confirmed Turns plus a distinct
third ready Turn context, immutable snapshot/history, branch switch plus
archive/restore guards, compile/review/approve/commit,
refresh/back-forward/recovery, and unchanged Traditional Writing Mode
behavior. Every mutation remained behind existing services and operation
authorities.

## 0D5-C status

0D5-C implementation is documented in `PHASE_0D5_C.md` and `PHASE_0D5_C_DELIVERY_REPORT.md`. The shell, branch controls, multi-Turn continuation, immutable history, recovery display, URL state, and Traditional Mode guard are implemented. Targeted tests and the isolated contract harness pass; sealing awaits real-browser three-Turn evidence. 0D5-D is not entered.

0D5-C-RC1 real-browser evidence is documented in `PHASE_0D5_C_RC1.md` and `PHASE_0D5_C_RC1_DELIVERY_REPORT.md`. Browser entry and branch lifecycle checks pass; durable three-Turn progression remains blocked by fixture readiness, so 0D5-C stays unsealed.

0D5-C-RC2 is documented in `PHASE_0D5_C_RC2.md` and `PHASE_0D5_C_RC2_DELIVERY_REPORT.md`. The authoritative ready fixture and two-confirm/Turn-3 browser loop pass; durable-result-before-response-loss recovery remains open, so 0D5-C is not sealed and 0D5-D is not entered.

0D5-C-RC3 is documented in `PHASE_0D5_C_RC3.md` and `PHASE_0D5_C_RC3_DELIVERY_REPORT.md`. Durable completion before response loss, single-Confirm recovery, restored result, and safe continuation are verified. **Phase 0D5-C: SEALED. Phase 0D5-D: NOT ENTERED.**

## 0D5-D1 status

0D5-D1-RC1 is PASSED and D1 is SEALED. It adds only durable Candidate review
authority and the existing commit path's approval gate. D2 is AUTHORIZED by
the seal but is not entered in this change.

## 0D5-D2 status

0D5-D2 is implemented and SEALED in `PHASE_0D5_D2.md` and
`PHASE_0D5_D2_DELIVERY_REPORT.md`. `PHASE_0D5_D_RC1.md` and its delivery report
record the complete browser matrix: normal approval-to-completion, Reject,
Compile/Review/Commit response-loss recovery, read-only Refresh/Back/Forward,
scope isolation, and Traditional Mode smoke. At the D2 closure, Phase 0D5-D
was SEALED and Phase 0D5-RC was authorized but not yet entered; the final RC
seal below supersedes that historical gate.

## Final RC seal

0D5-RC is independently accepted in `PHASE_0D5_RC.md` and
`PHASE_0D5_RC_DELIVERY_REPORT.md`. The real Chromium usable loop, Branch
product workflow, three-Turn continuity, immutable History, Candidate review,
approval-gated Commit/Completion, exactly-once recovery, read-only navigation,
scope and Traditional isolation, accessibility/responsive behavior, and
network/filesystem boundaries are verified.

**Phase 0D5-RC: PASSED. Phase 0D5: SEALED.** No later phase is entered.
