# Phase 0D6-A-RC2 Delivery Report

## Outcome

**PASSED — READY TO SEAL**

RC2 closes all five RC1 seal blockers.  Phase 0D6-B remains **NOT AUTHORIZED**.

## Changed Files

- `story-os-demo/system/chapter_lifecycle_service.py`
- `story-os-demo/system/chapter_lifecycle_adapters.py`
- `story-os-demo/system/narrative_branch_lifecycle_service.py`
- `story-os-demo/system/revision_service.py`
- `story-os-demo/web/chapter_lifecycle_routes.py`
- `story-os-demo/web/schemas.py`
- `story-os-demo/web/app.py`
- `story-os-demo/tests/test_phase0d6a_chapter_lifecycle.py`
- `story-os-demo/tests/test_phase0d6a_rc2_closure.py`
- `docs/planning/PHASE_0D6_A_RC2.md`
- `docs/planning/PHASE_0D6_A_RC2_DELIVERY_REPORT.md`

## Defects Found and Root Causes

1. Branch archive and Chapter create used unrelated locks, leaving a
   post-fence/pre-publication TOCTOU window.
2. Claims did not bind actual branch, planning, or completion bytes, so replay
   could adapt to changed authority.
3. Pre-publication failures could leave orphan Version/Canon assets and
   successful operations retained staging.
4. Timeline IDs were not fully validated while timeline-specific locks guarded
   project-global chapter storage.
5. Lock owner creation/reclamation did not close owner-write and stale-owner
   failure paths.
6. No production lifecycle route, DTO, or real Traditional/Simulator adapter
   delegated to the shared authority.
7. Windows `os.kill(pid, 0)` was unsafe for lock-owner liveness probing and
   interrupted real process competition tests; Windows now uses `OpenProcess`.

## Implementation Summary

- Added immutable branch/planning/completion authority snapshots and adjacent
  publication fencing.
- Added a shared project/timeline authority lock used by create and archive.
- Blocked archive while a bound Chapter operation is incomplete.
- Restricted project-global Chapter creation to the authoritative main
  timeline and validated all identifiers.
- Added pre-publication rollback, staging cleanup, result-write recovery, and
  stale lock recovery.
- Added thin Traditional/Simulator adapters plus a no-store GET/POST lifecycle
  route and validated DTO.

## Evidence

### Concurrency

Archive-first, create-first, claim/successor/staging/Version/Canon/publication
interruption, archive crash/retry, and a `threading.Barrier` create/archive race
all preserve a single serial authority order.

### Freshness and Completion Authority

Canonical planning bytes and commit-result bytes are stored in the immutable
claim.  Same-path replacement, revision/content changes, deletion, corruption,
status transitions, and deterministic threaded races fail closed.

### Filesystem and Scope Isolation

The success diff is an exact seven-path allowlist.  Replay and operation
conflict produce zero successor diff.  Version, Canon, publication, and result
failures have deterministic recovery assertions.  No temp/owner/lock residue
remains.  Second-project snapshots and non-main timeline checks prove zero
cross-scope mutation; the success allowlist proves sibling branch and previous
authority files remain unchanged.

### Route, DTO, Adapter, and Recovery

Traditional and Simulator adapters return one durable result for the same
operation/request.  Route retries create one successor; malformed operation IDs
fail validation before writes.  Eight-point recovery remains intact and now
revalidates newly-bound authorities.

## Validation Ledger

| Validation | Passed | Failed | Skipped | Exit |
|---|---:|---:|---:|---:|
| Modified Python `py_compile` | 7 modules | 0 | 0 | 0 |
| RC1 + RC2 focused | 89 | 0 | 0 | 0 |
| 0D5 + ChapterCommit + Revision + real/static guards | 86 | 0 | 0 | 0 |
| Branch lifecycle regression | 32 | 0 | 0 | 0 |
| VersionManager + Planning regression | 19 | 0 | 0 | 0 |
| **Total pytest** | **226** | **0** | **0** | **0** |

Category labels do not overlap across the four pytest commands.

## Safety Ledger

- Provider calls: 0
- External network calls: 0
- Real project writes: 0
- Real data writes: 0
- Chroma writes: 0
- Frontend authority changes: 0
- Production UI changes: 0
- ChapterCommitService changes: 0
- Candidate authority changes: 0
- Review authority changes: 0
- New dependencies: 0
- Git write operations: 0

## Remaining Limitations

- Chapter assets are project-global; non-main timelines intentionally cannot
  create successor chapters in Phase 0D6-A.
- This phase wires the backend authority boundary only.  No progression UI or
  Phase 0D6-B readiness behavior was added.

## Seal Decision

Phase 0D6-A-RC2 is **PASSED — READY TO SEAL**.  Owner may seal Phase 0D6-A.
Phase 0D6-B remains **NOT AUTHORIZED** and was not entered.
