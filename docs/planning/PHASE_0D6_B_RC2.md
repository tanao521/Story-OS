# Phase 0D6-B-RC2 — Scope-Aware Orphan Classification & Fail-Closed Recovery

## Scope

RC2 fixes exactly the three production defects exposed by FV1:

1. scope-aware lifecycle orphan classification;
2. phase-without-effect replay fail-closed;
3. archive scanning and validation of all progression artifacts.

Sealed Phase 0D6-A lifecycle semantics and resolver behavior are unchanged.

## Shared Scope Classification

`system/cross_chapter_scope.py` is a read-only internal helper. It validates
all supplied scope fields before deciding whether an artifact is current,
unrelated, ambiguous, or corrupt. A mismatch is considered unrelated only
when the supplied fields are themselves valid. Missing or conflicting scope
cannot be used to hide corruption.

Readiness and archive use the same classification rule:

- clearly other project/timeline/sibling Branch/Chapter: ignore;
- current target scope: block incomplete or corrupt evidence;
- ambiguous, malformed, or scope-conflicting evidence: fail closed.

No artifact is repaired, deleted, or selected by mtime/lexical order.

## Phase/Effect Contract

During replay, durable phases are treated as promises about already-published
effects:

- effect exists and phase is missing: validate the immutable effect and write
  only the missing phase;
- phase exists and effect is missing: return `CORRUPT_OPERATION`;
- transition/result/completed phases additionally require their preceding
  plan, transition, and result effects;
- plan scope, Chapter, and bound context fingerprint are checked before reuse.

The planner is never rerun to replace an effect promised by an existing phase.

## Archive Contract

Archive now aggregates every `<operation>.json`, `.phase.json`, and
`.result.json` basename before making a decision. Current-scope claim-only,
phase-only, result-only, malformed, incomplete, mismatched, or non-terminal
bundles block archive with the existing safe recovery error. Clearly unrelated
scope artifacts are ignored. A valid completed bundle must still pass the full
claim/result/plan/transition binding validator.

## Verification Matrix

`tests/test_phase0d6b_fv1.py` retains the original FV1 assertions, and
`tests/test_phase0d6b_rc2.py` adds:

- current and unrelated lifecycle orphan cases;
- ambiguous and scope-conflicting evidence;
- incomplete unrelated claims and scoped phase orphans;
- plan/transition/result/completed phase-without-effect cases;
- current archive orphan blocking and registry immutability;
- unrelated archive scope isolation and valid terminal archive validation.

All readiness assertions use before/after filesystem snapshots.

## Non-Goals

- No ChapterLifecycleService or sealed resolver changes.
- No new readiness status family, UI, Provider, Candidate, Review, Commit,
  Canon, Chroma, Obsidian, non-main successor, or Turn schema redesign.
- No unrelated broad-suite failure repair.
- No Git, network, or real-project writes.

