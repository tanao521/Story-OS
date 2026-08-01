# Story OS — Phase 0D8-FV-RC2 Delivery Report

## Final conclusion

**PASS — READY TO RESUME REMAINING PHASE 0D8-FV GATES**.

RC2 closed the integrity-anomaly approval defect without weakening strict
Commit. Decision-ID mismatch, malformed history, conflicting history, and
decision provenance mismatch now fail before legacy review mutation, approval
creation, optional-polish retry, or Commit orchestration. Legitimate MISSING
approval still creates one fresh immutable decision, and the normal visible
strict Commit control still produces exactly one CommitRun and one Canon
revision with identical approval provenance.

The remaining FV gates were not resumed in this task. Phase 0D8-SEAL was not
entered, and no Git commit, push, PR, or remote mutation was performed.

## Execution configuration

- Single agent, medium reasoning, fresh isolated Edge/CDP fixture per browser
  scenario.
- Production workspace: `D:\novel\StoryOS\story-os-demo`.
- Evidence root: `.tmp/phase0d8fv-rc2-authority/`.
- Existing RC1 selection behavior and request-changes lineage were preserved.

## Reproduced pre-fix sequence and root cause

The pre-fix sequence was:

```text
persisted approved Y
→ decision record identity becomes anomalous
→ visible POST /api/review/approve {force:false,polish:null}
→ update_review_status creates replacement APPROVED decision
→ force/no-polish retry continues with replacement authority
→ strict Commit creates CommitRun and Canon
```

The strict validator did not accept the mismatched decision itself. The defect
was upstream: approval orchestration treated an integrity anomaly as an
opportunity to create fresh authority during the same operation.

## RC2 repair

The repair is limited to the approval boundary:

- `web/routes.py` now resolves exact identity and folds decision state before
  calling `update_review_status` or creating/reusing approval authority.
- `INVALID`, `CONFLICTING`, decision-ID mismatch, and provenance mismatch return
  their exact error code and stop immediately.
- `system/review_decision_service.py` detects a decision record whose persisted
  `decision_id` differs from its immutable filename and exposes
  `APPROVAL_DECISION_ID_MISMATCH` to the route guard.
- `system/review_gate.py` can reuse an already valid exact APPROVED decision;
  it does not mint a replacement during re-approval.
- A narrow legacy compatibility path remains only for incomplete test/legacy
  targets that cannot represent exact authority; real `find_current_review_target`
  results are exact and always guarded.

No changes were made to `web/static/app.js`, selection convergence, Commit
provenance schema, Canon schema, Provider integrations, or timeline authority.

## Integrity versus lifecycle classification

| State | RC2 behavior |
|---|---|
| `MISSING` | explicit approval may create one fresh APPROVED decision |
| `STALE` after valid revision/content change | explicit approval may create fresh authority |
| `REJECTED` followed by explicit later approval | allowed as lifecycle behavior |
| `INVALID` | `APPROVAL_INVALID`, no replacement or Commit |
| `CONFLICTING` | `APPROVAL_CONFLICTING`, no replacement or Commit |
| decision-ID mismatch | `APPROVAL_DECISION_ID_MISMATCH`, no replacement or Commit |
| scope/provenance mismatch | `APPROVAL_PROVENANCE_MISMATCH`, no replacement or Commit |

The exact decision state wins over the legacy chapter-level `approved`
projection. The projection cannot authorize replacement authority or strict
Commit.

## Edge/CDP acceptance evidence

### Case A — decision-ID mismatch

Evidence: `.tmp/phase0d8fv-rc2-authority/decision-id-mismatch-rc2-final.json`.

- Y remained visibly identifiable before and after the attempt.
- The only approval request was the normal first request:
  `{"force":false,"polish":null}`.
- The response/log showed `APPROVAL_DECISION_ID_MISMATCH`.
- No replacement decision was created.
- Strict audit was empty; CommitRun count was `0`, Canon count was `0`.
- The anomalous decision file remained unchanged after the operation.

The direct focused test also invoked the force/no-polish retry and received the
same fail-closed error with zero decision/Commit/Canon delta.

### Case C — INVALID and CONFLICTING regression

Evidence:

- `.tmp/phase0d8fv-rc2-authority/malformed-decision-rc2-final.json`
- `.tmp/phase0d8fv-rc2-authority/conflicting-decision-rc2-final.json`

Both cases displayed a truthful error in the log, emitted no replacement
approval request, recorded no strict Commit audit, and produced `0` CommitRuns
and `0` Canon indexes. The legacy `approved` projection could not authorize
Commit.

### Case B — normal fresh approval control

Evidence: `.tmp/phase0d8fv-rc2-authority/normal-approval-rc2-final.json`.

- Fresh-review Y was opened and visibly selected.
- The real UI emitted the two expected requests, including the no-polish retry.
- Exactly one new APPROVED decision, one CommitRun, and one Canon index were
  persisted.
- Commit and Canon approval provenance were byte-for-byte equal at the shared
  identity/provenance fields.
- Commit ID: `ef7adac497c6cebf`; Canon revision:
  `canon-chapter-001-v001`.

## Deterministic tests

New focused tests in `tests/test_phase0d8fv_rc2_integrity.py` cover decision-ID
mismatch, force retry, INVALID, CONFLICTING, provenance mismatch, zero durable
mutation, and legitimate MISSING approval.

- RC2 focused matrix: **52 passed, 0 failed**.
- Expanded review/route/decision/Commit/version/frontend matrix:
  **132 passed, 0 failed**.
- Full suite: **2483 passed, 0 failed, 0 skipped**, normal pytest exit,
  **2483 tests collected**, 2 pre-existing unknown-mark warnings.

## Strict Commit and mutation closure

The valid control path remained:

```text
POST approve
→ exact approval identity
→ ChapterCommitService.commit_chapter
→ validate_approved_commit
→ CommitRunStore + RevisionService Canon
```

For failed anomaly cases, mutation counts were:

```text
decision delta = 0
CommitRun delta = 0
Canon revision delta = 0
```

For the normal control, mutation counts were exactly one decision, one
CommitRun, and one Canon revision. Strict Commit consumed only the explicitly
valid exact authority.

## Static and production audit

- Python compile/import checks for changed Python and tests: passed.
- `node --check web/static/app.js`: passed; app.js was not changed by RC2.
- `git diff --check`: passed; only pre-existing line-ending warnings appeared.
- Final `web/static/app.js` SHA256: `0096CCD034D0E55F87595A112EF8C0FB480CBEBC95471F0EF688C6C557AEF33C`.
- Authorized RC2 production files: `web/routes.py`,
  `system/review_gate.py`, `system/review_decision_service.py`.
- Tests/evidence helpers: `tests/test_phase0d8fv_rc2_integrity.py`,
  `tests/_phase0d8fv_final_gates.py`, and retained `.tmp` evidence.
- Earlier dirty worktree changes were preserved and not reclassified as RC2.

## Cleanup ledger

- Owned Edge processes: `0`.
- Fixture Python servers: `0`.
- Temporary Edge profiles: `0`.
- Fixture ports `7867` and `7868`: free.
- Failed startup residue from one transient CDP harness attempt was identified
  by its exact `phase0d8fv_final_edge_` profile, stopped, and removed; it did
  not enter product verification or alter evidence conclusions.
- Earlier FV and RC1 evidence roots were preserved.

## Invariant closure

| Invariant | Result |
|---|---|
| decision-ID mismatch cannot mint replacement approval | **PASS** |
| integrity anomaly cannot Commit in the same operation | **PASS** |
| force/no-polish retry cannot bypass integrity failure | **PASS** |
| INVALID and CONFLICTING cannot be auto-repaired | **PASS** |
| legacy approved projection cannot authorize replacement or Commit | **PASS** |
| legitimate fresh approval remains available | **PASS** |
| strict Commit consumes only explicitly valid authority | **PASS** |
| failed anomaly validation creates no Commit or Canon mutation | **PASS** |

## Remaining FV gates

RC2 authorizes resuming the following, but they were intentionally not run in
this task because the authorization separately prohibits resuming them without
Owner direction:

1. Gate 5 fingerprint mismatch
2. Gate 3 delayed Commit response
3. Gate 4 duplicate Commit replay

The next action requires a separate Owner authorization to resume those gates.

## SEAL reconciliation (current state)

RC2 current result: **PASSED**. The remaining-gates language above is retained
as historical RC2-era scope; RC3, RC4, Gate 4, and Phase 0D8-SEAL were
subsequently completed under separate authorization.
