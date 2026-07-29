# Phase 0D6-A-RC1: Shared Chapter Lifecycle Authority Final Verification

## Status: PARTIALLY PASSED — NOT SEALED

Date: 2026-07-28

## Verified in this RC

- `get_selected_version()` and `active_canon()` are pure reads in the covered
  fixture cases.
- Chapter lifecycle operation claims are immutable for a request fingerprint;
  a changed request with the same operation ID raises `OPERATION_CONFLICT`.
- Lifecycle creation stages the chapter internally, initializes Version and
  Canon assets, then publishes the chapter.  Resolver state remains
  `NEXT_CHAPTER_MISSING` before publication.
- Eight one-shot recovery points replay with stable authority bytes:
  claim, successor resolution, staging, Version initialization, Canon
  initialization, publication, durable result publication, and the completed
  phase marker boundary.
- Same-operation replay, result-without-phase repair, existing-successor
  handling, and a barrier-synchronised two-thread create/create race passed.
- `COMMITTED_WITH_WARNINGS` permits creation; recovery-required and invalid
  commit states fail closed.  Previous chapter content/version/Canon fixture
  checks passed.

## RC Fixes

1. A lifecycle phase is now recorded only after its corresponding action
   succeeds.  This prevents a replay from skipping a failed publication.
2. Chapter assets are staged before the chapter file is published, so a
   partially initialized successor is not resolver-visible as ready.
3. The filesystem lock now removes its owner artifact on exit and does not
   treat another thread in the same process as a reentrant lock holder.
4. Canon initialization supports lifecycle staging without writing the chapter
   file before publication.

## Remaining Seal Blockers

- No RC evidence currently proves create-vs-branch-archive behavior.
- No RC evidence currently proves planning-change freshness fencing.
- No RC evidence currently proves completion-authority corruption/change races.
- No RC evidence currently proves cross-timeline/project mutation isolation or
  full filesystem-diff protection across every successful, failed, concurrent,
  and recovery case.
- No Traditional adapter is wired to this service; current evidence only shows
  two service instances sharing the same authority.  There is no lifecycle
  route/DTO integration to verify.

Accordingly, Phase 0D6-B remains **NOT AUTHORIZED**.
