# Phase 0D6-D — Cross-Chapter Branch/Memory/Vector Continuity and Recovery

**Status:** SEALED — Phase 0D6-D complete; the implementation-planning status is superseded by `PHASE_0D6_D_SEAL.md` (2026-07-30)  
**Recovered by:** Phase 0D7-P audit, 2026-07-30  
**Entry gate:** Phase 0D6-C SEALED  
**Authority boundary:** Main-timeline continuity and recovery only

## Objective

Make the existing main-timeline simulator loop truthful across a chapter boundary. A committed chapter already produces a successor with branch identity, but its lifecycle result currently reports memory and vector readiness as `not_ready`. 0D6-D supplies durable, scoped continuity and deterministic recovery before any future expansion to non-main timelines, Provider Live, or a redesigned workspace.

## First implementation slice: 0D6-D-A

**Closed loop:** Given a completed main-timeline chapter and its active branch, successor creation records exactly one authority-bound branch-memory continuity snapshot. Re-reading after restart either returns that same verified snapshot or returns a stable recovery-required state. The ready/not-ready projection must be derived from this durable authority, never inferred in the browser.

### In scope

- Main timeline only (`timeline_id == "main"`).
- Active, non-archived branch only.
- Bind source chapter, successor chapter, branch id/revision, selected source version, and canon revision where authoritative.
- Idempotent creation, conflict detection, and recoverable incomplete-operation handling.
- Focused regression tests for success, replay, stale branch authority, interrupted creation, corrupt/missing snapshot, and scope isolation.
- Minimal read-model/API projection only if required to expose a truthful readiness/recovery state in the existing simulator progression UI.

### Out of scope

- Non-main chapter creation or turn start.
- Provider configuration, consent, execution, network calls, or token/budget changes.
- New Traditional/Simulator unification, large UI redesign, chapter-quality feature, dependency, or data migration unrelated to the D-A invariant.
- Replacing sealed 0D6-C lifecycle, readiness, or Chromium acceptance contracts.

## Dependency plan

| Slice | Work | Gate |
|---|---|---|
| D-A | Branch-memory carry-forward and recovery authority | Must pass focused persistence/recovery matrix before D-B. |
| D-B | Vector manifest/rebuild continuity tied to D-A authority | Must not mark vector ready unless the scoped manifest is durable and recoverable. |
| D-FV | End-to-end continuity verification | Run after D-B; browser validation only for affected existing UI behavior. |
| D-SEAL | Reconcile evidence and decide seal | Requires D-FV pass and no open recovery ambiguity. |

## Expected authority owners

Primary: `system/branch_narrative_memory_service.py`, `system/chapter_lifecycle_service.py`, and the relevant continuity projection/service.  
Later D-B: `system/vector_index_lifecycle.py` plus its scoped-manifest authority.

Exact files must be confirmed from the current call graph before editing. The historical 0D6-D brief named older service paths; this recovered brief intentionally follows the current branch-scoped implementation rather than treating obsolete file names as authority.

## Acceptance criteria

1. A successful D-A successor contains a verifiable, scope-bound continuity record.
2. Replaying the same operation has no duplicate or divergent record.
3. Wrong project, timeline, branch, revision, chapter, or source/canon authority fails closed.
4. Missing/corrupt/incomplete continuity data produces a deterministic recovery code, not a false-ready state.
5. Existing main-timeline progression behavior remains intact; non-main remains explicitly unsupported.
6. No provider/network call occurs in development or verification.

## Validation plan

1. Focused unit/service tests for D-A authority and recovery.
2. Focused lifecycle/readiness regression tests.
3. D-B vector tests after D-A passes.
4. Full regression and Chromium matrix only in D-FV, according to the then-current sealed baseline.

## Execution model and cost guardrail

Use one GPT-5.6-terra agent at medium-high reasoning for D-A; use high reasoning for D-B only if vector-manifest recovery requires it. Keep all provider budgets at zero and run no real provider calls. Do not commit, push, or alter external resources without separate user authorization.

## Stop conditions

- Discovery that D-A requires non-main successor creation, a live provider call, or a broad UI redesign: stop and return for scope approval.
- A new defect in sealed 0D6-C contracts: stop, document evidence, and request a dedicated repair-chain authorization.
- Authority ownership cannot be made unambiguous from current code/tests: stop before mutation and issue a focused design question.
