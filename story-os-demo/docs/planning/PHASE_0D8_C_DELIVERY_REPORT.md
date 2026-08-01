# Story OS — Phase 0D8-C Delivery Report

Status: **IMPLEMENTED; service/API verification PASS; bounded browser UI acceptance PARTIAL (fixture harness limitation)**

This phase closes the invariant `approved identity == committed identity`; an
approval mismatch now fails closed before any canonical write. Phase 0D8-FV and
SEAL were not started.

## Delivered

- Added `system/commit_authority.py` as the single exact-identity gate.
- Approval identity is immutable and includes project, timeline, branch,
  chapter, source type, source version id, content fingerprint, decision id,
  decision timestamp and validation timestamp.
- The gate re-reads the append-only decision, requires `CURRENT` + `APPROVED`,
  verifies the selected pointer, source path, source type, version and fresh
  fingerprint, and re-validates immediately before the snapshot/core write.
- Added explicit fail-closed taxonomy for missing, stale, invalid, conflicting,
  rejected, mismatched, drifted and re-review-required approvals.
- Commit runs and canonical revision metadata persist the exact approval
  provenance. Duplicate replay returns the same provenance instead of creating
  a second canonical commit.
- The human approval route now creates/reuses an immutable decision and passes
  that exact identity into `ChapterCommitService`.
- The review panel shows the approved version and fingerprint and explains that
  commit requires the same selected identity.

The legacy `commit_chapter` source-authority path remains available for existing
internal/compatibility callers. The human approval route and the new
`commit_approved_chapter` API require the exact approval authority; no mutable
review projection alone can authorize a commit.

## Files

- `system/commit_authority.py`
- `system/chapter_commit_service.py`
- `system/commit_run_store.py`
- `system/revision_service.py`
- `web/routes.py`
- `web/static/app.js`
- `tests/test_phase0d8c_commit_authority.py`

## Verification

- Focused Phase 0D8-C regression suite: **11 passed**.
- Combined affected 0D7/0D8-A/B/C suite: **126 passed in 7.02s**.
- `node --check web/static/app.js`: passed.
- Python byte-compilation for all changed Python modules/tests: passed.
- `git diff --check`: passed (only existing line-ending normalization warnings).

The isolated Chromium fixture was opened through the visible Story OS UI; the
manual version selector and immutable approval decision were exercised. The
fixture has no polish-capable provider and the in-app dialog adapter exposes an
accept-only confirmation, so its optional AI-polish branch could not be used to
complete the auto-submit path. Exact approval-to-commit success and all
selection/content-drift fail-closed cases are covered by the focused service and
API regressions above. The fixture emitted two pre-existing narrative-memory
path warnings; they are outside 0D8-C and did not mutate the project under test.

No Git commit, push, PR, FV, or SEAL action was performed.
