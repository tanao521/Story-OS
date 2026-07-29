# Phase 0D5-D1-RC1

## Candidate Review Authority, Concurrency, Recovery and Commit-Gate Closure

Status: PASSED.

This RC closes only the D1 seal evidence. It does not add Candidate Review UI,
Commit UI, Chapter Completion UI, or D2 implementation.

### Authority contract

- Operation authority is immutable and bound to a canonical request fingerprint.
- Candidate versions are read-only review inputs.
- The decision journal is first-writer-wins per Candidate.
- Durable result and phase artifacts are separate and replayable.
- Corrupt, forked, missing, or mismatched review chains return
  `REVIEW_CHAIN_INVALID` and fail closed.

### Recovery matrix

The review service exposes deterministic fault hooks for:

1. after operation authority claim;
2. after Candidate snapshot;
3. after first freshness validation;
4. after review decision publication;
5. after durable result publication;
6. before the completed phase marker.

Each test uses a temporary ProjectRoot, injects the fault once, creates a new
service instance, and replays the same operation ID. It verifies unchanged
authority bytes, one decision, one durable result, stable request/outcome
fingerprints, and completed recovery phase.

Decision-without-result recovery reuses the one immutable decision. Result-
without-phase recovery returns the same result and repairs only the phase
marker; it does not publish a second decision or invoke a second commit.

### Concurrency and freshness

Approve/approve and approve/reject use atomic immutable publication. The first
durable writer wins; the loser receives an already-decided or decision-conflict
error. Review publication performs a second freshness fence after the first
validation, so Candidate supersede and Branch archive races fail closed.

Candidate/source bytes, Canon revision, Branch registry revision, Branch
lifecycle, scope, Candidate state, and review-chain authority are validated
before a new decision or commit.

### Commit gate

Pending, rejected, stale, superseded, archived, and invalid-chain Candidates
cannot reach `ChapterCommitService`. A valid durable approval reaches the
existing service exactly once. When a durable commit result already exists,
replay recovers that result before re-evaluating the review gate, so a later
stale/unreadable review or missing phase cannot duplicate the commit.

### Read and route boundaries

`SimulatorLoopStateService` projects review status and approval flags from
durable review authority. Candidate UI state is not an approval source.

`POST /api/narrative-chapter/candidates/{candidate_id}/review` and Candidate
read responses use a no-store cache header and fixed safe error envelopes. They
do not expose tracebacks, absolute paths, operation artifact paths, provider
details, or Chroma internals.

### Exit state

Phase 0D5-D1-RC1: PASSED

Phase 0D5-D1: SEALED

Phase 0D5-D2: AUTHORIZED, NOT ENTERED
