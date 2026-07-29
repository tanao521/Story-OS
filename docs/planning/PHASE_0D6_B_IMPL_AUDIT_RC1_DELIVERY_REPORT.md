# Phase 0D6-B-IMPL-AUDIT-RC1 Delivery Report

## Outcome

**PARTIALLY PASSED — IMPLEMENTATION FIX REQUIRED**

The existing implementation has the intended backend direction and preserves
the tested 0D6-A sealed Chapter lifecycle behavior, but it is not yet
authority-closed. The audit found P0 lifecycle-operation selection and replay
binding gaps plus P1 partial-recovery and archive-terminal gaps. No production
repair was authorized or performed.

## Audited Files

- `docs/planning/PHASE_0D6_A_SEAL.md`
- `docs/planning/PHASE_0D6_A_RC2.md`
- `docs/planning/PHASE_0D6_A_RC2_DELIVERY_REPORT.md`
- `docs/planning/PHASE_0D6_B.md`
- `story-os-demo/system/chapter_lifecycle_service.py`
- `story-os-demo/system/narrative_branch_lifecycle_service.py`
- `story-os-demo/system/narrative_branch_store.py`
- `story-os-demo/system/narrative_turn_service.py`
- `story-os-demo/system/narrative_turn_store.py`
- `story-os-demo/system/narrative_turn_context.py`
- `story-os-demo/system/narrative_turn_planner.py`
- `story-os-demo/system/narrative_turn_preview.py`
- `story-os-demo/system/narrative_action_feasibility.py`
- `story-os-demo/system/cross_chapter_readiness_service.py`
- `story-os-demo/system/cross_chapter_turn_start_service.py`
- `story-os-demo/web/chapter_progression_routes.py`
- `story-os-demo/web/chapter_lifecycle_routes.py`
- `story-os-demo/web/narrative_turn_routes.py`
- `story-os-demo/web/schemas.py`
- `story-os-demo/web/app.py`
- `story-os-demo/tests/test_phase0d6b_authority.py`
- the focused 0D6-A/Branch/Narrative Turn regression files

## Pre-existing Production Changes

At audit start, the worktree already contained the two cross-chapter services,
progression route, app/schema registration, and Branch archive hook, alongside
38 tracked changed files and many untracked historical phase files. These were
treated as audit subjects. No existing production file was deleted, reverted,
overwritten, or repaired.

## Pre-existing Test Changes

`tests/test_phase0d6b_authority.py` already existed with ten focused tests. The
audit ran it unchanged and identified the untested authority gaps described
below.

## Call-Chain Findings

### Readiness

GET is routed through the new progression router into the readiness service.
It reads completion, branch, lifecycle operation files, resolver projection,
Turn context, and Turn plans. The tested path is pure and no-store. The service
then performs a second directory scan because the sealed resolver does not
return a lifecycle operation ID.

### Start

POST validates the DTO, acquires Chapter timeline authority, Branch registry,
and a start-operation lock, re-reads readiness, claims the operation, binds
Turn context, delegates planner/feasibility/preview/store, publishes one plan
and one `planned -> awaiting_action` transition, writes a result, and marks
completed. Client successor and readiness fingerprint are checked before the
claim.

### Archive

Branch archive acquires the same Chapter timeline authority then registry lock,
checks Chapter lifecycle safety, checks progression operations, and only then
mutates the Branch registry. The lock order is compatible with 0D6-A.

## Authority-Compliant Behaviors

- Readiness GET is pure in the focused zero-diff test.
- Successor assets are checked through the sealed resolver projection and not
  created by the readiness path.
- Start is explicit POST-only with caller-supplied operation ID.
- Client Chapter IDs are assertions; the server computes fresh readiness.
- Existing Context Binder, Planner, Feasibility, Preview, and Turn Store are
  reused.
- Start does not confirm a Turn or write Candidate, Review, Commit, Canon,
  Chroma, Chapter, Version, Provider, or UI state.
- Same operation replay and different-request conflict pass focused tests.
- One initial plan and one awaiting-action transition are produced in the
  tested success path.
- 0D6-A focused and Branch/Turn regression tests pass.

## Authority Conflicts

1. Readiness selects `sorted(matching)[0]` after scanning lifecycle operations.
The resolver does not return an operation ID, and same-successor completed
operations are not compared for claim/result authority equality.
2. Lifecycle claim/result/phase linkage is incomplete: operation ID, result
operation/project, request successor, and resolver projection are not all
cross-validated.
3. Completed start result replay trusts the result file and repairs a missing
phase without validating result, plan, transition, claim, scope, and
fingerprint binding.
4. Archive treats any result file as terminal; result-without-completed-phase
is not blocked.
5. Plan/transition recovery uses `turn_started` rather than separate durable
effect phases and has no dedicated transition fault boundary.
6. Multiple valid initial plans for one successor are not declared corrupt;
the implementation chooses one lexically.

## Missing Behaviors

- authoritative resolver-to-operation association;
- orphan phase/result corruption classification;
- explicit planning/source/Canon status distinctions;
- existing-corrupt-Turn status code;
- plan/transition/result integrity validation on replay;
- deterministic transition-phase recovery matrix;
- external initial-Turn writer serialization;
- complete archive scope/result-phase matrix.

## 0D6-A Sealed Boundary Result

**No sealed regression established.** Chapter create/archive lock order,
completion/planning/branch authority, main-timeline restriction, lifecycle
claim/result schema, and resolver behavior remain present. The focused
0D6-A/Branch/Narrative Turn regression passed 259 tests. The identified issues
are 0D6-B authority gaps and must not be repaired by redefining 0D6-A.

## Validation Ledger

| Validation | Passed | Failed | Skipped | Exit |
|---|---:|---:|---:|---:|
| 0D6-B focused | 10 | 0 | 0 | 0 |
| 0D6-A + Branch + Narrative Turn focused | 259 | 0 | 0 | 0 |
| Modified 0D6-B Python `py_compile` | 6 modules | 0 | 0 | 0 |
| `git diff --check` | clean of whitespace errors | 0 | n/a | 0 |

The full repository suite was not required by this audit prompt. A prior broad
run in the same dirty worktree reported 2,239 passed, 33 failed, and 7
skipped; those failures were not altered or hidden.

## Safety Ledger

- Production code changes in this audit: 0
- Test code changes in this audit: 0
- Provider calls: 0
- External network calls: 0
- Real project/data writes: 0
- Chroma writes: 0
- Obsidian writes: 0
- Production UI changes: 0
- New dependencies: 0
- Git write operations: 0

## Recommended Next Action

Owner should authorize a bounded P0/P1 repair pass covering lifecycle
operation authority association, replay binding validation, explicit
plan/transition/result recovery phases, and archive result/phase validation.
The repair must preserve 0D6-A sealed semantics and add focused corruption,
drift, archive, and cross-scope tests before any 0D6-B acceptance decision.

## Implementation Authorization Decision

**Do not declare 0D6-B passed and do not enter the next phase.** The minimum
decision is `PARTIALLY PASSED — IMPLEMENTATION FIX REQUIRED` pending Owner
approval for the repair plan.
