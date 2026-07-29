# Phase 0D6-A-SEAL

## Seal Decision

**Phase 0D6-A is PASSED & SEALED.**

Owner seal date: **2026-07-28**

Sealed object: **Phase 0D6-A — Shared Chapter Lifecycle Authority**

Historical RC status is preserved:

- Phase 0D6-A-RC1: `COMPLETED — PARTIALLY PASSED — NOT SEALED`
- Phase 0D6-A-RC2: `PASSED — ACCEPTED`

## Sealed Scope

This seal covers immutable lifecycle operation claims, branch/planning/
completion authority binding, publication-adjacent final fencing, staging-first
Chapter publication, exactly-once Version and Canon initialization, eight-point
fault recovery, same-operation durable replay, create/create concurrency,
create/branch-archive concurrency, filesystem boundaries, project/timeline/
branch isolation, stale-owner recovery, Traditional and Simulator adapters,
the lifecycle GET/POST route, DTO validation, and the shared
`ChapterLifecycleService`.

## Accepted Invariants

### Operation authority

- Operation ID is immutable for its request fingerprint.
- Same ID with a different request returns `OPERATION_CONFLICT`.
- Incomplete replay revalidates branch, planning, and completion authority.
- A completed result is a stable historical fact.

### Publication

- A Chapter is not resolver-visible before Version and Canon initialization.
- A final authority fence runs immediately before publication.
- Publication failure cannot leave a half-initialized successor.
- Previous Chapter text, Version, and Canon are not rewritten.

### Branch archive

- Chapter create and branch archive use the shared project/timeline authority
  lock.
- An incomplete Chapter operation bound to the target branch blocks archive.
- Archive-first and create-first produce one ordered, non-contradictory durable
  outcome.

### Scope

- Project identity must match `ProjectContext`.
- Project-global Chapter storage permits successor creation only on the
  authoritative `main` timeline.
- Non-main timelines fail closed before mutation.
- Sibling projects, timelines, and branches are not modified.

### Recovery

- A phase is recorded only after its durable action succeeds.
- A missing effect is never skipped because a phase exists.
- Result-without-phase repairs only the phase marker.
- Publication-without-result never republishes the Chapter.
- Terminal success leaves no staging, temp, lock, or owner artifact.

### Entry wiring

- Traditional and Simulator adapters are thin proxies to the shared service.
- Routes do not create Chapters directly.
- DTO scope and operation-ID validation occur before writes.
- Caller source is not part of lifecycle authority semantics.
- `ChapterCommitService` remains the Chapter commit authority.

## Final Validation Ledger

```text
Modified Python py_compile: 7 modules passed

RC1 + RC2 focused: 89 passed, 0 failed, 0 skipped, exit 0
0D5 + ChapterCommit + Revision + real/static guards: 86 passed,
  0 failed, 0 skipped, exit 0
Branch lifecycle regression: 32 passed, 0 failed, 0 skipped, exit 0
VersionManager + Planning regression: 19 passed, 0 failed, 0 skipped, exit 0

Total pytest: 226 passed, 0 failed, 0 skipped, exit 0
```

The seven `py_compile` modules are not included in the pytest total.

## Safety Ledger

```text
Provider calls: 0
External network calls: 0
Real project writes: 0
Real data writes: 0
Chroma writes: 0
Git write operations: 0
New dependencies: 0
Production UI changes: 0
Candidate authority changes: 0
Review authority changes: 0
ChapterCommitService semantic changes: 0
```

## Accepted Limitations

### Project-global Chapter storage

Chapter assets remain project-global.  Only the authoritative `main` timeline
may create successor Chapters; non-main timelines fail closed before mutation.
This is not full multi-timeline Chapter lifecycle support.  Any future
multi-timeline successor model requires a separately authorized storage and
migration phase.

### Backend authority only

This seal covers the backend lifecycle authority boundary.  It does not add
progression UI or Phase 0D6-B readiness behavior.

### Legacy helper

The legacy chapter helper remains as compatibility code.  It has no production
successor route caller in the current wiring.  Static-path guards remain in
place; it is not deleted or redefined as a second lifecycle authority.

## Explicit Non-Authorization

```text
Phase 0D6-B remains NOT AUTHORIZED.
```

This seal does not authorize readiness aggregation, cross-chapter Turn start,
progression UI, Provider Live, external model calls, Chroma or Obsidian
mutation, Candidate or Review authority changes, or multi-timeline successor
creation.

## State Index Note

The repository has no single authoritative phase-index/status file distinct
from the planning and delivery reports.  Therefore no unrelated roadmap or
historical planning document was rewritten.  The authoritative sealed state is
recorded here, while RC1 and RC2 reports retain their original conclusions.

## Post-RC2 Code Check

The final RC2 validation completed before this seal operation.  Since that
validation, no production Python, route, DTO, adapter, test, configuration, or
dependency file was changed; this operation adds this document only.

