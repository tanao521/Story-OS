# Phase 0D6 Implementation Brief

Current gate: **0D6-P PARTIALLY PASSED · IMPLEMENTATION BLOCKED · OWNER DECISION REQUIRED**.

## Objective

After owner decisions, reuse existing authorities to move explicitly from a
terminal Chapter N Commit to a ready Chapter N+1 context without frontend
identity generation, hidden initialization, duplicate Commit, or cross-scope
contamination.

## Prerequisite decision package

1. Numeric chapter number is accepted or rejected as the lifecycle identity.
2. Planning record identity is distinguished from lifecycle identity.
3. One shared Chapter create-or-resolve service is selected.
4. The meaning of `state.current_chapter` is fixed.
5. Initial Canon and Branch State carry-forward policies are fixed.
6. Warning classes and Turn-blocking rules are fixed.

No implementation slice may start before this package is approved.

## Proposed slices

### 0D6-A — Chapter lifecycle authority and adapters

- Objective: provide pure resolve plus exactly-once explicit create using the
  owner-approved identity.
- Allowed files: new lifecycle service/contracts/routes and focused tests;
  minimal Traditional adapter.
- Forbidden: frontend file creation, new Commit/Canon/Version authority.
- Authority owner: owner-approved Chapter lifecycle service.
- Mutation budget: one explicit create operation.
- Provider/network: 0/0.
- Tests: replay/collision/CAS/response-loss/cold-read.
- Browser: creation entry and recovery smoke.
- Entry: decision package approved.
- Exit: single shared mutation and pure resolver.
- Model: Terra; reasoning medium-high; single Agent.

### 0D6-B — Progression read model and readiness

- Objective: compose Commit, Chapter, Branch, Memory, Canon, Planning and
  Vector readiness without mutation.
- Allowed files: read models/adapters/tests.
- Forbidden: lifecycle or Commit mutation changes.
- Authority owner: existing services plus Chapter resolver.
- Mutation budget: 0.
- Provider/network: 0/0.
- Tests: warning classes, branch/chapter isolation, stale data.
- Browser: read-state smoke only.
- Entry: 0D6-A sealed.
- Exit: typed state machine projection.
- Model: Luna; reasoning medium; single Agent.

### 0D6-C — Explicit product navigation

- Objective: wire Completion to existing-target navigation or shared creation.
- Allowed files: Simulator UI/template/CSS and UI tests.
- Forbidden: identity generation or direct writes.
- Authority owner: 0D6-A/B APIs.
- Mutation budget: one user-triggered existing create call.
- Provider/network: 0/0.
- Tests: URL cleanup, accessibility, responsive, Traditional isolation.
- Browser: desktop/tablet/mobile.
- Entry: 0D6-B sealed.
- Exit: navigation is explicit and recoverable.
- Model: Luna; reasoning medium; single Agent.

### 0D6-D — Cross-chapter continuity and recovery

- Objective: bind same-Branch prior state/memory and preserve old History while
  excluding old Candidate/operation authority.
- Allowed files: read adapters, binder integration, recovery tests.
- Forbidden: new memory, Turn, Candidate, Review, Commit authority.
- Mutation budget: existing Turn only after `NEXT_CHAPTER_READY`.
- Provider/network: 0/0.
- Tests: A/B Branch isolation, warning repair, refresh/history.
- Browser: two-chapter continuity smoke.
- Entry: 0D6-C sealed.
- Exit: full continuity invariants pass.
- Model: Terra; reasoning medium-high; single Agent.

### 0D6-RC — Two-chapter final acceptance

- Objective: real Chromium Chapter N completion through Chapter N+1 Turn.
- Allowed files: fixture, acceptance scripts, reports; defect fixes only under
  explicit RC bounds.
- Mutation budget: exact user actions only.
- Provider/network: 0/0.
- Tests: focused authority regression and filesystem manifest.
- Browser: existing and missing-next-chapter, recovery, isolation,
  accessibility/responsive.
- Entry: A–D sealed.
- Exit: exactly-once and boundary evidence complete.
- Model: Terra; reasoning medium-high; single Agent.

## Stop rule

This brief is planning only. Phase 0D6-A remains not entered.

