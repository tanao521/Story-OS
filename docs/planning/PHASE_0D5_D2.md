# Phase 0D5-D2 — Candidate Compile, Review, Approval, Commit UI

## Scope

Integrate the sealed Candidate compiler, Candidate review authority, commit gate,
and Simulator Loop read model into the existing Simulator shell. This phase adds
no approval, candidate, commit, Canon, or vector authority.

## Delivered

- Candidate list/detail UI sourced from `GET /api/simulator/state` and the
  existing candidate-detail route.
- Compile, review, and commit controls call only the existing narrative chapter
  routes with a single in-memory operation id per in-flight action.
- Read-model preconditions are sent with compile; stale/scope/authority errors
  are rendered as safe actionable messages.
- Unknown mutation outcomes expose recovery by rereading state only; no action
  is repeated automatically.
- Approved-only native commit dialog has focus trapping, Escape, and return
  focus. Completion and next-chapter navigation follow authoritative state.
- URL holds scope, `view`, and `candidate_id` only; it never holds approval or
  operation identity.

## Closure

Phase 0D5-D2 implementation and the D-RC1 browser closure are complete. The
remaining RC1 matrix confirms reject blocking, one-shot Compile/Review/Commit
response-loss recovery, read-only refresh/history navigation, scope isolation,
and unchanged Traditional Writing Mode behavior. D2 is sealed; 0D5-RC is
authorized but not entered.

## Boundaries

Traditional Writing Mode remains on its existing UI and routes. No new
Candidate, Review, Commit, Canon, Chroma, provider, or external-network
authority was introduced.
