# Phase 0D5-D1

## Durable Candidate Review Authority and Commit Approval Gate

Status: SEALED after Phase 0D5-D1-RC1.

Candidate versions remain immutable. Review decisions are written once under
`data/narrative_candidate_review`, with immutable operation authority,
mutable phase, and durable result separated. `approved` is required before the
existing `ChapterCommitService` path; no additional commit channel is introduced.

The read model resolves review state from durable review authority rather than
Candidate UI state. RC1 closes authority, concurrency, recovery, freshness,
review-chain, commit-gate, route-safety, and Traditional Mode isolation
evidence. No review UI or chapter-completion work is included.

Phase 0D5-D2 is AUTHORIZED by this seal but was not entered in this change.
