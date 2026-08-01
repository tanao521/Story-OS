# Story OS — Phase 0D8-FV-RC3 Delivery Report

## Final conclusion

**PASS — READY TO RESUME REMAINING PHASE 0D8-FV GATES**.

RC3 closes the same-version fingerprint-drift defect. An existing approval for
exact Version Y at H1 is now distinguished from legitimate cross-version
STALE lifecycle state when the same Y file has current fingerprint H2. The
normal approval operation fails before legacy review mutation, replacement
decision creation, optional-polish retry, or strict Commit.

Gate 3 delayed Commit and Gate 4 duplicate replay were not resumed in this
task. RC3 does not authorize Phase 0D8-SEAL.

## Execution configuration

- Single agent, medium reasoning.
- Fresh Edge/CDP fixture, project, profile, and loopback ledger per scenario.
- Evidence root: `.tmp/phase0d8fv-rc3-fingerprint/`.
- Production freeze respected except the narrowly authorized RC3 repair in
  `web/routes.py`.

## Reproduced H1/H2 defect

The corrected fixture preserved the exact Y decision at:

```text
H1 = 017b2a88ba37d8bf0683d390bfa3ab85c34f7468c5a99fe00769a82fb0730a47
```

Then it mutated the authoritative Y content in place to:

```text
H2 = 72ab62adf6b3e84fd23527fba9c95a95f903c454ae256aeb27781c2e40496a4b
```

Before RC3, the visible flow created a replacement H2 approval and produced
one CommitRun and one Canon revision. Evidence of the pre-fix reproduction is
preserved at `.tmp/phase0d8fv-final-closure/gate5-fingerprint-mismatch-corrected.json`.

## Root cause and repair

`web/routes.py` classified the exact H1 decision as ordinary `STALE` after the
same Y content changed, allowing `update_review_status()` to create D2. RC3
adds a same-version history comparison before legacy review mutation:

- same project/timeline/branch/chapter/source/version plus a different stored
  fingerprint returns `APPROVAL_FINGERPRINT_MISMATCH`;
- response metadata includes source version, decision ID, approved H1 and
  current H2 fingerprints;
- no replacement decision, CommitRun, Canon revision, lineage transition,
  selected-version change, or legacy fallback is performed;
- distinct-version STALE/MISSING lifecycle remains eligible for explicit fresh
  approval.

The existing `create_decision()` current-identity check and strict Commit
validator remain the revalidation boundaries for content changes after route
entry. No decision history is rewritten and no in-place repair workflow was
added.

## Edge/CDP acceptance

### Case A — corrected same-version fingerprint mismatch

Evidence: `.tmp/phase0d8fv-rc3-fingerprint/gate5-fingerprint-mismatch.json`.

- Y remained selected and visibly rendered as `STALE`.
- Normal request was captured:
  `POST /api/review/approve {"force":false,"polish":null}`.
- The response/log reported `APPROVAL_FINGERPRINT_MISMATCH`.
- No force/no-polish request was issued by the UI after the fail-closed first
  response; the focused test directly verified that
  `{"force":true,"polish":false}` returns the same error.
- Strict audit: empty.
- Decision delta: `0`.
- CommitRun delta: `0`.
- Canon delta: `0`.

### Case B — distinct-version fresh approval control

Evidence: `.tmp/phase0d8fv-rc3-fingerprint/distinct-version-control.json`.

Fresh-review Y emitted the normal two-request visible flow and produced one
new immutable approval, one CommitRun, and one Canon revision. Commit and Canon
approval provenance matched on identity, fingerprint, decision ID, decision
status/type, timestamps, and transition provenance. This confirms RC3 does not
block legitimate new-version approval.

### Case C — RC2 anomaly regressions

Evidence:

- `.tmp/phase0d8fv-rc3-fingerprint/decision-id-mismatch.json`
- `.tmp/phase0d8fv-rc3-fingerprint/malformed-decision.json`
- `.tmp/phase0d8fv-rc3-fingerprint/conflicting-decision.json`

All three remained fail-closed with zero replacement decisions, zero strict
Commit audit entries, zero CommitRuns, and zero Canon revisions.

## Deterministic tests and matrices

New/updated focused test coverage is in
`tests/test_phase0d8fv_rc2_integrity.py`, including same-version H1/H2 drift,
force retry, zero mutation, provenance metadata, and MISSING lifecycle control.

The exact RC3 focused selection was:

```text
tests/test_phase0d8c_commit_authority.py
tests/test_phase0d8fv_rc1_selection.py
tests/test_review_decision_service.py
tests/test_review_transition_service.py
tests/test_review_transition_api.py
tests/test_phase0d8fv_rc2_integrity.py
```

Result: **53 passed, 0 failed**.

The exact RC2-era expanded selection was the union of these review/route,
Commit, version, and frontend files:

```text
test_api_canonical_routes.py
test_chapter_committer.py
test_chapter_commit_service.py
test_commit_manual_version.py
test_commit_prefers_edited.py
test_commit_rollback_injection.py
test_commit_selected_version.py
test_manual_editor.py
test_phase0d8c_commit_authority.py
test_phase0d8fv_rc1_selection.py
test_phase0d8fv_rc2_integrity.py
test_review_auto_archive.py
test_review_decision_service.py
test_review_gate.py
test_review_quality_integration.py
test_review_transition_api.py
test_review_transition_service.py
test_version_adoption_service.py
test_version_manager.py
test_version_manager_compatibility.py
test_version_manager_manual.py
test_version_writer_facade.py
```

Result: **133 passed, 0 failed**. The historical RC1 expanded count of 163
covered a broader earlier selection; the RC2/RC3 selection is a narrower
review/route/decision/Commit/version/frontend union, so 133 and 163 are not
interchangeable totals.

Full suite: the first run had one unrelated transient narrative registry-lock
timeout with 2483 other tests passing. The failing node passed immediately when
rerun alone, and the complete rerun then finished with **2484 passed, 0 failed,
0 skipped**, 2 pre-existing unknown-mark warnings, normal pytest exit.

## Strict-path and provenance audit

The valid distinct-version control followed:

```text
POST approve
→ exact Y identity
→ ChapterCommitService.commit_chapter
→ validate_approved_commit
→ CommitRunStore + RevisionService Canon
```

The fingerprint-drift case stopped before this path. No legacy
`commit_chapter` fallback occurred. The normal control produced exactly one
CommitRun and one Canon revision with equal approval provenance.

## Static, asset, and production audit

- Python compile checks: passed.
- `node --check web/static/app.js`: passed; app.js was not changed.
- `git diff --check`: passed with pre-existing line-ending warnings.
- app.js SHA256: `0096CCD034D0E55F87595A112EF8C0FB480CBEBC95471F0EF688C6C557AEF33C`.
- RC3 production file changed: `web/routes.py` only.
- Tests-only changes: RC3 focused test and underscore fixture/harness helpers.
- No Provider, Canon, memory, vector, timeline, dependency, configuration,
  commit, push, or PR action occurred.

## Cleanup ledger

- Owned Edge processes: `0`.
- Fixture servers: `0`.
- Temporary Edge profiles: `0`.
- Fixture ports `7867/7868`: free.
- Temporary fixture projects were removed after each scenario.
- Earlier FV, BH1, RC1, RC2, and final-closure evidence roots were preserved.

## Invariant closure

| Invariant | Result |
|---|---|
| same-version fingerprint drift cannot mint replacement approval | PASS |
| same-version fingerprint drift cannot Commit in same operation | PASS |
| force retry cannot bypass fingerprint integrity | PASS |
| historical H1 approval remains unchanged | PASS |
| distinct Y can receive legitimate fresh approval | PASS |
| strict Commit consumes only current exact approval | PASS |
| failed fingerprint validation creates no Commit or Canon | PASS |
| RC2 INVALID/CONFLICTING/ID/provenance guards remain green | PASS |
| RC1 selection convergence baseline remains green | PASS |

## Remaining FV gates

RC3 authorizes resuming only:

1. Gate 5 fingerprint-mismatch verification
2. Gate 3 delayed Commit response
3. Gate 4 duplicate Commit replay

This run revalidated Gate 5 but intentionally did not resume Gate 3 or Gate 4,
and did not enter Phase 0D8-SEAL. Separate Owner authorization remains
required for those actions.

## SEAL reconciliation (current state)

RC3 current result: **PASSED**. The remaining-gates language above is retained
as historical RC3-era scope; RC4, Gate 4, and Phase 0D8-SEAL were subsequently
completed under separate authorization.
