# Phase 0D8 Implementation Brief — Version-Bound Human Review Decision and Revision Closure

**Status:** PLANNING AUTHORITY ONLY — implementation not started
**Entry gate:** 0D7 SEALED
**Authority source:** `POST_0D7_PRODUCT_LOOP_AUDIT_REPORT.md` (2026-08-01)

## Current phase status

**Phase 0D8: SEALED - COMPLETE**

**Phase 0D8-FV: PASSED**

**Next product phase: NOT AUTHORIZED**

The planning-status text below is retained as historical entry-state context;
it is not the current phase status.

## Objective

Close the pre-commit human revision loop so a durable human decision binds an
exact work-version identity and Commit consumes that same identity or fails
closed.

## Invariants

```text
Approval of Version X never approves Version Y.
Approved identity = Committed identity, or Commit fails closed.
Evidence state is not a Review decision.
```

The reviewed/approved identity must bind project, timeline, branch, chapter,
source type, source-version label, content fingerprint, and decision identity.
Assembly-evidence identity may be recorded as consulted advisory evidence, but
must never become automatic approval or Commit authority.

## Bounded slices

| Slice | Objective | Authority |
| --- | --- | --- |
| 0D8-A | Durable append-only work-version decisions and stale-decision detection | HUMAN_DECISION_AUTHORITY |
| 0D8-B | Request-changes from X, revised work-version Y, lineage, and re-review display | TRANSITION_AUTHORITY / DERIVED_DISPLAY |
| 0D8-C | Exact approval-to-Commit revalidation and fail-closed selection/content drift | TRANSITION_AUTHORITY |
| 0D8-FV | Race, drift, browser, affected regression, and full-suite verification | Verification only |
| 0D8-SEAL | Evidence reconciliation | Documentation only |

## Required behavior

```text
Review X -> request changes -> revised Y -> fresh Y review -> approve Y -> commit Y
```

- Preserve X and Y as distinct versions; never overwrite or transfer approval.
- Require a fresh decision for Y.
- Keep evidence generation explicit and advisory; MISSING/STALE must remain
  truthful and must not silently generate evidence.
- Revalidate decision, source version, fingerprint, and selection at commit.
- Reject stale decisions, content drift, candidate mismatch, conflicting
  transitions, and concurrent selection drift.

## Excluded

- Provider Live, credentials, external calls, dependencies, and model changes.
- Non-main timeline continuation, vector redesign, memory/canon authority changes.
- Automatic rewrite, approval, rejection, commit, or publication.
- Broad Traditional/Simulator unification or workspace redesign.
- Reopening sealed 0D6 or 0D7 contracts.

## Authority classification

| Artifact | Classification |
| --- | --- |
| Version / Canon / Commit | SOURCE_AUTHORITY |
| Work-version review decision | HUMAN_DECISION_AUTHORITY |
| Request-changes lineage | TRANSITION_AUTHORITY |
| Assembly and quality evidence | DURABLE_ADVISORY_EVIDENCE |
| Review display | DERIVED_DISPLAY |
| Vector | REBUILDABLE_CACHE |

## Validation

Use deterministic tests for identity, stale decisions, X→Y lineage, and
fail-closed Commit. Browser acceptance is limited to the 0D8-B visible
workflow. Run full regression only in 0D8-FV. No live Provider calls.

## Model plan

| Slice | Model | Reasoning | Agents | Role |
| --- | --- | ---: | ---: | --- |
| 0D8-A | Terra | High | 1 | Review-decision authority |
| 0D8-B | Terra | Medium | 1 | Targeted workflow display |
| 0D8-C | Terra | High | 1 | Commit identity gate |
| 0D8-FV / SEAL | Terra | Medium | 1 | Verification / reconciliation |

## Current slice result

0D8-A is implemented under explicit Owner authorization. The durable decision
log and exact-version read model are now available; existing review routes
write a compatibility projection plus the immutable decision record when an
authoritative version file is present. No Commit enforcement or revision
lineage was added.

## Next

Await separate explicit Owner authorization for **0D8-B**. Do not begin 0D8-C,
0D8-FV, or 0D8-SEAL automatically.
