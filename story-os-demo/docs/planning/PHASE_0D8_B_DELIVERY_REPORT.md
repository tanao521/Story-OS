# Phase 0D8-B Delivery Report

## Final conclusion

**PASSED — Phase 0D8-B implementation complete.** Request-changes lineage is
now a durable transition authority layered on top of the accepted 0D8-A exact
work-version decision authority. 0D8-C, 0D8-FV, and 0D8-SEAL were not started.

## Authoritative objective

The bounded workflow is implemented:

```text
exact X -> human REQUEST_CHANGES -> durable REQUESTED transition
         -> explicit manual save -> distinct Y -> immutable X->Y event
         -> Y MISSING decision / RE_REVIEW_REQUIRED -> fresh 0D8-A decision
```

`REQUEST_CHANGES` is not encoded as `REJECTED`, and no decision is created by
requesting changes.

## Production files changed

- `system/review_transition_service.py` — append-only transition events,
  identity revalidation, lifecycle folding, conflict/drift detection, and
  derived re-review state.
- `system/manual_editor.py` — optional frozen-source preflight and explicit
  transition metadata on a newly-created manual work version.
- `web/schemas.py` — request-changes, revision-attach, and manual-save
  transition fields.
- `web/routes.py` — request/inspect/attach transition APIs, decision read-model
  lineage, and transition-aware manual-save path.
- `web/static/app.js` and `web/templates/index.html` — targeted request-changes
  action, transition status, revised-from/fresh-review display, and stale-view
  response guard reuse.

## Transition schema and lifecycle

Each event under `data/review_transitions/` contains a schema version, event
identity, transition identity, operation identity, timestamp, actor/note,
exact frozen source identity, and (for `REVISION_CREATED`) exact result
identity.  The read model folds immutable events into:

```text
REQUESTED | REVISION_CREATED | SUPERSEDED | INVALID | CONFLICTING
```

Same-operation replay is idempotent.  A second active transition for the same
exact X, malformed records, incompatible event histories, source drift, and
result-identity conflicts fail closed.  The minimal implementation does not
invent broad branching support; later transitions reconstruct naturally as
`X -> Y` and `Y -> Z` without rewriting earlier events.

## Exact identity and Version Y creation

- X is captured from the authoritative version file using the 0D8-A identity:
  project, timeline, branch, chapter, source type, exact version label, and
  content fingerprint.
- The fingerprint and exact source are revalidated immediately before request
  persistence, before manual Y creation, and before lineage attachment.
- Y uses the existing `create_manual_version` / `VersionWriterFacade` path;
  it receives a new version identity and fingerprint and records the frozen
  transition ID plus source identity in its payload.
- X is never overwritten.  An unrelated existing version cannot be attached
  because its explicit transition metadata and source identity must match.

## Decision and evidence isolation

- X `APPROVED` or `REJECTED` remains bound to X.
- Y starts with no exact current decision.  If X has a historical decision,
  0D8-A may report Y as `STALE`, but the transition read model derives
  `re_review_required: true` and the UI says “Fresh review required”.
- Y can receive an independent 0D8-A decision; no decision is copied.
- Evidence remains advisory and version-bound.  Requesting changes and opening
  Y do not generate evidence or decisions.

## Drift, concurrency, and stale-response behavior

- Frozen X selection/content drift rejects the request or attachment.
- Two tabs cannot claim the same active X with incompatible operation IDs.
- Competing result claims and malformed/conflicting event histories fail closed.
- The existing request-ownership guard prevents delayed X evidence/decision
  responses from changing a currently displayed Y state.

## Browser acceptance

Using a fresh isolated fixture project and local browser profile, the bounded
matrix verified:

1. Opened `manual_v001` (X) and clicked **请求修改**.
2. Saved a distinct manual revision and opened the resulting Y.
3. Visible state showed: `Revised from manual_v001 · Fresh review required · no
   decision inherited (MISSING)`.
4. A delayed X response was released after switching to Y; the Y text remained
   unchanged and continued to show fresh review required.
5. No Commit, Provider, evidence generation, or external network operation was
   invoked.

## Validation

- Focused 0D8-B transition/API tests: **14 passed**, 0 failed.
- Combined 0D8-A, transition, manual-editor, version-manager/writer,
  review-gate, route, and sealed 0D7 evidence matrix: **97 passed**, 0 failed.
- Python compile/import checks: passed.
- `node --check web/static/app.js`: passed.
- `git diff --check`: passed (only existing line-ending normalization
  warnings were reported).
- Full repository regression was intentionally deferred to 0D8-FV.

## Safety ledger and remaining boundaries

- No ChapterCommitService or Commit eligibility code changed.
- No Provider, Canon, memory, vector, 0D6, or sealed 0D7 authority changed.
- Browser fixture service and tabs were closed; the isolated fixture lived only
  outside the user project in the system temporary area.
- No Git commit, push, roadmap change, or seal action was performed.

Invariant status:

```text
Request changes bound to exact X: CLOSED
X preserved and Y distinct: CLOSED
Immutable X->Y lineage: CLOSED
No decision inherited by Y: CLOSED
Y requires fresh exact decision: CLOSED
Evidence not transferred: CLOSED
Delayed X responses cannot overwrite Y display: CLOSED
Commit enforcement unchanged/deferred to 0D8-C: CLOSED
```

Next action requires separate Owner authorization for 0D8-C.
