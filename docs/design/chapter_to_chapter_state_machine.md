# Chapter-to-Chapter State Machine

This is a design contract only. No production state machine is implemented.

## Core states

| State | Authoritative evidence | Allowed reads | Allowed mutation | Primary action | Block/recovery | URL/view |
|---|---|---|---|---|---|---|
| `CHAPTER_ACTIVE` | No terminal Commit result | Turn, History, Candidate | Existing chapter mutations | Continue chapter | Existing recovery | Current chapter |
| `CHAPTER_COMMITTING` | Non-terminal Commit operation phase | Operation/read model | No new Chapter mutation | Read operation | Recover same operation | Commit recovery |
| `CHAPTER_COMPLETE` | Terminal Commit result and active Canon | Completion, History | Resolve next only | Start next chapter | None | `view=complete` |
| `CHAPTER_COMPLETE_WITH_WARNINGS` | `committed_with_warnings` | Warning/task state | Repair or resolve per warning class | Review warnings | Durable Commit run | `view=complete` |
| `NEXT_CHAPTER_RESOLVING` | Stable source Commit ID/fingerprint plus expected chapter-set fingerprint | Chapter registry projection | None | Wait/read | Re-read | Completion |
| `NEXT_CHAPTER_AVAILABLE` | Existing authoritative chapter record with valid source and readiness | Target chapter context | None | Open explicitly | Fail closed on drift | Target chapter |
| `NEXT_CHAPTER_MISSING` | Pure resolver proves no target | Creation capability | None | Open creation flow | None | Creation entry |
| `NEXT_CHAPTER_CREATION_REQUIRED` | Missing target and owner-authorized create capability | Plan and predecessor evidence | Explicit create only | Create chapter | Missing owner blocks | Creation entry |
| `NEXT_CHAPTER_CREATING` | Durable create operation is non-terminal | Operation result/phase | Same-operation replay only | Recover | Read durable operation | Creation recovery |
| `NEXT_CHAPTER_RECOVERY_REQUIRED` | Outcome unknown or result/phase mismatch | Durable result and chapter set | No new operation ID | Recover existing | Fail closed | Recovery |
| `NEXT_CHAPTER_READY` | Target identity, source, Canon policy, Branch State and readiness all valid | Turn context | Existing Turn mutation | Start first Turn | Re-resolve on drift | Narrative Turn |
| `NEXT_CHAPTER_BLOCKED` | Missing/contradictory authority or blocking warning | Diagnostics | Repair only | Resolve blocker | Typed reason | Completion/setup |

`NEXT_CHAPTER_CREATING` is retained because any future creation must be
exactly-once. There is no current production implementation for it.

## Warning classification

| Classification | Navigation | Creation | Start Turn |
|---|---|---|---|
| `COMPLETED_READY_FOR_NEXT_CHAPTER` | yes | if missing and explicitly authorized | when ready |
| `COMPLETED_WITH_NON_BLOCKING_WARNINGS` | yes | yes | yes with notice |
| `COMPLETED_BUT_MEMORY_STALE` | yes | yes | no until repair or explicit deterministic-only owner policy |
| `COMPLETED_BUT_VECTOR_STALE` | yes | yes | no under current readiness gate |
| `COMPLETED_BUT_RECOVERY_REQUIRED` | no | no | no |
| `NEXT_CHAPTER_BLOCKED` | no | no | no |

The current `committed_with_warnings` value does not encode these classes, so
it cannot by itself authorize the next Turn.

## Fixture-validated state transitions (2026-07-28)

Based on temporary fixture probes:

1. **CHAPTER_COMPLETE → NEXT_CHAPTER_AVAILABLE** (Fixture A):
   - Trigger: `chapter_progression.next_chapter_available = True`
   - Evidence: `chapter_002.md` exists, `chapter_002_versions.json` exists
   - Action: Frontend `nextChapter()` → URL `chapter_id=2`
   - No backend API called — pure URL navigation
   - Classification: **EXISTING_NEXT_CHAPTER_NAVIGATION**

2. **CHAPTER_COMPLETE → NEXT_CHAPTER_MISSING** (Fixture B/C):
   - Trigger: `chapter_progression.next_chapter_available = False`
   - Evidence: No `chapter_002.md` file
   - Action: Button disabled with title "Next-chapter navigation is not available from the backend."
   - Cold-start reads:
     - `list_versions()`: PURE_READ (0 delta)
     - `get_selected_version()`: **HIDDEN_MUTATION** (+1 file: versions index)
     - `read_active_canon()`: PURE_READ (0 delta)
     - `active_canon()`: **LEGACY_INITIALIZATION** (error — no chapter file)
   - No creation flow available

3. **NEXT_CHAPTER_RESOLVING → BLOCKED** (All fixtures):
   - Trigger: `SimulatorLoopStateService.build()` KeyError: 'revision'
   - Root cause: Branch manifest JSON lacks expected `revision` field
   - Impact: Read model cannot aggregate branch readiness for cross-chapter projection
   - Classification: **IMPLEMENTATION_BUG** — must be fixed before 0D6-A

## Current product state coverage

The current product directly expresses only:
- `CHAPTER_COMPLETE` (via `commit.status` in read model)
- A file-existence based available/missing signal (`next_chapter_available`)

All other states are design candidates for future implementation. The
`completion` view is rendered by `simulator-candidate-review.js:renderCompletion()`
and driven by `SimulatorLoopStateService.build()` read model aggregation.