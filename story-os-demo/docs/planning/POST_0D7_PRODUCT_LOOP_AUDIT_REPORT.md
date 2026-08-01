# Post-0D7 Product Loop Closure Audit Report

**Status:** PASSED — NEXT PHASE RECOVERED WITH REQUIRED REVISION
**Date:** 2026-08-01
**Mode:** read-only / planning-only; production, runtime, and test diff are 0.

## Final decision

```text
NEXT AUTHORITATIVE PHASE = Phase 0D8 — Version-Bound Human Review Decision and Revision Closure
```

The revision loop is **PARTIALLY COMPLETE**. The highest-value gap is the
unsafe hand-off from work-version review to commit. `0D8` is newly allocated:
0D7 is sealed and no existing 0D8/0E definition exists.

## Baseline and authority

```text
0D6-A: SEALED
0D6-B: SEALED
0D6-C: SEALED
0D6-D: SEALED
0D7:   SEALED
```

`PHASE_0D7_SEAL.md` is CURRENT AUTHORITY. 0D7 A/B/RC1/FV reports are
HISTORICAL AUDIT EVIDENCE. `POST_0D6_ROADMAP_AUDIT_REPORT.md` and
`PHASE_0D7_P_AUDIT_REPORT.md` are HISTORICAL / SUPERSEDED next-phase
recommendations. Provider Live, non-main continuation, workspace redesign, and
export are UNEXECUTED BUT VALID / DEFERRED. Existing 0D8/0E authority is ABSENT.

## Actual loop and gaps

| Link | State | Evidence |
| --- | --- | --- |
| Work versions | IMPLEMENTED | `version_manager.py` persists versions and selected pointer. |
| Assembly evidence | DURABLE_ADVISORY_EVIDENCE | 0D7 binds source label/fingerprint and displays safe states. |
| Work-version review | PARTIAL | `review_gate.py` stores one chapter-level review record. |
| Request changes → revised version | MISSING | Manual versions exist; no X→Y decision lineage or re-review transition. |
| Approval | PARTIAL / UNSAFE | No fingerprint, candidate, evidence ID, scope tuple, or invalidation. |
| Commit | IMPLEMENTED BUT NOT APPROVAL-BOUND | Commit records source hash but does not require matching approval. |
| Canon revision | IMPLEMENTED, separate | `RevisionService` has immutable candidates and candidate-bound approval. |

The work-version review record contains source type/version but is retargeted by
`prepare_review_record()` to the selected version. It has only `pending`,
`approved`, and `rejected`; work-version `request_changes` is absent.

`RevisionService` already demonstrates the correct Canon-only pattern:
append-only candidates, `request_changes`, candidate-bound approval, and stale
baseline rejection. It does not govern the pre-commit work-version review gate.

`approve_review()` prepares the current target then calls
`ChapterCommitService.commit_chapter()` without a source-version argument.
Commit otherwise resolves the current selection and never compares it with a
human approval. Therefore both invariants are OPEN:

```text
Approval of Version X must never approve Version Y.
Approved identity = Committed identity, or Commit fails closed.
```

## Drift matrix

| Scenario | State |
| --- | --- |
| X reviewed, Y selected before approval | OPEN |
| X approved, Y selected before commit | OPEN |
| Content changes after evidence | CLOSED for display: 0D7 returns STALE |
| Canon candidate or baseline changes | CLOSED in `RevisionService` |
| Delayed evidence response | CLOSED by 0D7-B-RC1 |
| Delayed work decision / concurrent tabs | OPEN |

The UI shows selected version and evidence but not a durable decision bound to
that identity, X→Y lineage, re-review required, or the identity Commit will
consume. Required frontend work is TARGETED WORKFLOW CLOSURE, not redesign.

## Candidate matrix

| Candidate | Direct value | Readiness | Risk | Priority |
| --- | ---: | ---: | ---: | ---: |
| A. Version-bound revision/re-review closure | 5 | 5 | 3 | **1** |
| B. Narrative evidence expansion | 3 | 4 | 2 | 2 — DEFERRED |
| C. Non-main continuation | 4 | 1 | 5 | 5 — DEFERRED |
| D. Provider Live | 2 | 2 | 5 | 6 — DEFERRED |
| E. Traditional/Simulator alignment | 3 | 2 | 4 | 4 — DEFERRED |
| F. Manuscript/export | 2 | 3 | 3 | 3 — DEFERRED |

## Phase shape and next authorization

```text
Review X -> request changes -> revised Y -> fresh Y review -> approve Y -> commit Y
```

- 0D8-A: durable exact work-version review decisions and stale-decision detection.
- 0D8-B: request-changes, X→Y lineage, and re-review display.
- 0D8-C: exact approval-to-commit revalidation and fail-closed drift.
- 0D8-FV / SEAL: verification and documentation only.

Version, Canon, and Commit remain SOURCE_AUTHORITY. Evidence remains
DURABLE_ADVISORY_EVIDENCE. Human decisions become HUMAN_DECISION_AUTHORITY.
Vector remains REBUILDABLE_CACHE. Provider, multi-timeline, and a redesign are
not required.

| Slice | Model | Reasoning | Agents |
| --- | --- | ---: | ---: |
| 0D8-A | Terra | High | 1 |
| 0D8-B | Terra | Medium | 1 |
| 0D8-C | Terra | High | 1 |
| 0D8-FV / SEAL | Terra | Medium | 1 |

Authorize **0D8-A only**. Do not implement automatically.
