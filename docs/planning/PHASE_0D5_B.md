# Phase 0D5-B — Simulator Read Model & Product State Aggregation

Status: **PASSED**  
Phase 0D4: **SEALED**  
Phase 0D5-A: **PASSED**  
Phase 0D5-C: **NOT ENTERED**

## Delivered

`SimulatorLoopStateService` is a read-only, explicitly scoped projection over existing Turn, Branch, Candidate, Commit, Vector-manifest, and Canon authorities. `GET /api/simulator/state` returns the projection with `Cache-Control: no-store` and a safe error envelope.

The projection contains scope, stage, branch readiness, Turn/current result/history summary, Candidate list/current Candidate/freshness/review status, commit durable result/recovery, chapter progression, and the explicit `REQUIRED_BACKEND_GAP_FOR_APPROVAL` marker.

## Recovery contract

The service detects incomplete durable records and returns one of `TURN_RECOVERY_REQUIRED`, `CANDIDATE_RECOVERY_REQUIRED`, `COMMIT_RECOVERY_REQUIRED`, or `READY_FOR_NEXT_ACTION`. It never resumes, rewrites, creates, approves, compiles, commits, or indexes anything while reading state.

## Authority and isolation

* Turn data comes from `NarrativeTurnStore` and its transition journal.
* Branch lifecycle/active pointer/registry revision come from `BranchLifecycleService` read projections.
* Candidate data comes from Phase F version artifacts and provenance.
* Commit status comes from Phase F commit operation authority/result artifacts.
* Canon revision comes from the new non-mutating `RevisionService.read_active_canon` projection method.
* Vector readiness is read from the existing branch manifest; Chroma is not opened and manifest internals are not returned.

No frontend-only authority, URL inference, localStorage authority, approval fake, ChapterCommitService bypass, direct Canon/Chroma write, Provider call, or Git write was introduced.

