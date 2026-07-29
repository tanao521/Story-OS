# Phase 0D6-B-FV1 — Final Authority & Recovery Verification

## Verification Goal

FV1 is a verification-only phase. It confirms the RC1 authority, readiness
purity, fault-recovery ordering, replay integrity, initial-Turn arbitration,
archive terminal checks, scope isolation, filesystem boundary, and regression
gates. No production implementation is changed by FV1.

## RC1 Baseline

RC1 was recorded as:

- lifecycle bundle association and resolver consistency implemented;
- completed start replay validates claim, plan, transition, result, scope, and
  fingerprints;
- shared `initial-turn` lock wired to progression start and Narrative Turn
  confirmation;
- archive requires a validated terminal start bundle;
- RC1 focused: 15 passed;
- 0D6-A + Narrative Turn + Branch: 259 passed;
- 0D5/routes/commit-revision/static guards: 105 passed.

## Verification Matrix

### Lifecycle bundle and readiness

Covered by `tests/test_phase0d6b_authority.py` and
`tests/test_phase0d6b_fv1.py`:

- valid unique completed bundle and resolver successor;
- claim/phase/result partial records;
- malformed and mismatched result evidence;
- duplicate same-successor conflict;
- GET readiness filesystem zero-diff;
- client assertion mismatch and planning/source drift before claim write.

The valid, duplicate, partial, malformed, and current-scope cases fail closed.
FV1 also exposes a scope-isolation defect: an unscoped result-only artifact in
another timeline is treated as global corruption.

### Fault recovery

The deterministic fault hooks were exercised after claim, plan effect, plan
phase, Turn delegation, transition effect, transition phase, result effect,
result phase, and completed phase. The passing boundaries replay to one plan,
one sequence-0 transition, one result, and a completed phase with no temporary
or lock residue.

FV1 additionally exposes that a `plan_published` phase can be followed by plan
deletion and replay can reconstruct a new plan instead of failing closed.

### Completed replay

Completed replay tests reject tampered result and transition fingerprints,
preserve the historical result, and do not create a second plan or transition.

### Concurrency and archive

RC1 regression coverage verifies start/start first-writer behavior and the
shared component-local lock path. Incomplete and result-without-completed
operations block archive.

FV1 exposes that a result-only progression artifact with no claim is ignored
by archive validation in the current target scope.

### Filesystem boundary and non-goals

FV1 verifies no readiness writes, no operation claim on failed assertions, no
temporary/owner residue after successful replay, and no use of Provider,
network, real project data, Chroma, Obsidian, UI, Git, Candidate, Review,
Canon, or Chapter commit authority.

## FV1 Decision

FV1 is **not ready to seal**. The three failed gates are genuine production
implementation defects, not weakened or skipped tests. They require the
minimal RC2 scope below.

## Minimal RC2 Scope

1. Make lifecycle orphan classification scope-aware while preserving fail
   closed behavior for current-scope and unscoped corruption.
2. Make phase-without-effect replay validate and recover only an identical,
   provable immutable effect; otherwise return `CORRUPT_OPERATION`.
3. Make archive scan all progression artifacts and reject current-scope
   result/phase or other orphan corruption, while ignoring unrelated scopes.

0D6-A sealed lifecycle semantics remain unchanged.

