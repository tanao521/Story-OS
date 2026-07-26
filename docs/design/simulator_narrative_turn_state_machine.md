# Simulator Narrative Turn — State Machine

> Phase 0D4-A implementation artifact.  Contracts and store implemented in
> `core/contracts/narrative_turn.py` and `system/narrative_turn_store.py`.
>
> **Phase 0D4-A-FIX-RC** revises this map to reflect the deterministic
> transition ordering (sequence + previous binding), the project-root
> operation authority, the fail-closed lifecycle corruption handling, and
> the explicit terminal-vs-non-terminal classification of `blocked`.

**OWNER Decisions Applied:**
- Immutable Turn records + append-only lifecycle transition journal
- No in-place status updates on Plan/Validation/Result
- Current state derived from transition journal
- Plan creation is a non-canonical write (not read-only)
- **(FIX-RC)** Transition ordering is by `sequence`, not `occurred_at`
- **(FIX-RC)** `previous_transition_id` / `previous_transition_fingerprint`
  form a singly-linked chain validated on every append and every replay
- **(FIX-RC)** Operation authority is project-root; cross-branch /
  cross-timeline / cross-turn collisions are detectable
- **(FIX-RC)** `blocked` is terminal — a blocked Turn cannot be re-opened;
  the user must create a new Plan to take a different action
- **(FIX-RC2)** Lifecycle event path改为 sequence-only
- **(FIX-RC2)** Registry event 确定性 sequence journal 可重建
- **(FIX-RC2)** Active archive 多文件操作可恢复
- **(FIX-RC2)** State delta 递归冻结

## 1. Turn lifecycle state machine

```
                                  ┌─────────────┐
                                  │   planned   │ ← TurnPlan appended (non-canonical write)
                                  └──────┬──────┘
                                         │ user selects/enters action
                                         ▼
                                  ┌─────────────┐
                  ┌───────────────│awaiting_action│
                  │               └──────┬──────┘
                  │                      │ submit action
                  ▼                      ▼
            ┌──────────┐           ┌───────────┐
            │ superseded│           │ validating │
            └──────────┘           └─────┬─────┘
              (terminal)                  │
                          ┌───────────────┼───────────────┐
                          │               │               │
                          ▼               ▼               ▼
                   ┌─────────┐    ┌─────────────┐   ┌─────────┐
                   │ blocked │    │validated    │   │requires_│
                   └─────────┘    └──────┬──────┘   │clarify  │
                    (terminal)           │           └─────────┘
                                         │ preview requested
                                         ▼
                                  ┌───────────┐
                                  │ previewed  │
                                  └──────┬────┘
                                         │ user confirms (operation_id)
                                         ▼
                                  ┌───────────┐
                                  │ confirmed  │ ← immutable TurnResult + transition appended
                                  └──────┬────┘
                                         │ branch-local event log appended
                                         ▼
                                  ┌──────────────────┐
                                  │applied_to_branch  │ ← state delta proposed
                                  └──────┬───────────┘
                                         │ chapter compile includes this Turn
                                         ▼
                                  ┌──────────────────────┐
                                  │included_in_chapter    │
                                  └──────┬───────────────┘
                                         │ ChapterCommitService.commit_chapter()
                                         ▼
                                  ┌───────────┐
                                  │ committed │ (terminal; Canon updated globally)
                                  └───────────┘
```

**Terminal states (FIX-RC clarification):** `blocked`, `committed`,
`superseded`. No transition out of a terminal state is allowed. A Turn
in `blocked` cannot be re-opened; the user must create a new Plan to
take a different action.

## 2. Legal transitions

Each transition is persisted at
`data/narrative_turns/{timeline_id}/{branch_id}/transitions/{turn_id}/{sequence:08d}.json`
and is identified by **`sequence`** (not `transition_id`) on disk so that
two concurrent writers racing the same slot collide on the same path.

| From | To | Trigger | Side effect | sequence | previous binding |
| --- | --- | --- | --- | --- | --- |
| (none) | `planned` | `append_plan()` | **write**: immutable Plan record | n/a (Plan, not Transition) | n/a |
| `planned` | `awaiting_action` | user selects action entry | **write**: transition journal entry | 0 | `None` / `None` |
| `planned` | `superseded` | source changed / timeline changed / new plan created | **write**: transition journal entry; terminal | next | last transition id+fp |
| `awaiting_action` | `validating` | `append_validation()` | **write**: immutable Validation record + transition | next | last transition id+fp |
| `validating` | `blocked` | feasibility returns `blocked` | **write**: transition journal entry; **terminal** | next | last transition id+fp |
| `validating` | `validated` | feasibility returns `allowed` or `allowed_with_cost` | **write**: transition journal entry | next | last transition id+fp |
| `validating` | `requires_clarification` | feasibility returns `requires_clarification` | **write**: transition journal entry | next | last transition id+fp |
| `requires_clarification` | `awaiting_action` | user refines and resubmits | **write**: transition journal entry | next | last transition id+fp |
| `validated` | `previewed` | preview requested | **write**: transition journal entry | next | last transition id+fp |
| `previewed` | `confirmed` | confirm with `operation_id` | **write**: immutable Result record + transition | next | last transition id+fp |
| `confirmed` | `applied_to_branch` | branch-local state delta materialized | **write**: transition journal entry | next | last transition id+fp |
| `applied_to_branch` | `included_in_chapter` | chapter compile selects this Turn | **write**: transition journal entry | next | last transition id+fp |
| `included_in_chapter` | `committed` | `ChapterCommitService.commit_chapter()` succeeds | **write**: transition journal entry; terminal | next | last transition id+fp |

**Note:** `allowed_with_cost` is a validation outcome, lifecycle enters `validated`.

## 3. Illegal transitions

| Attempt | Result |
| --- | --- |
| `confirmed` → `planned` | `ILLEGAL_TRANSITION` |
| `committed` → any | `TERMINAL_STATE` (terminal) |
| `blocked` → any | `TERMINAL_STATE` (terminal; FIX-RC: must create a new Plan) |
| `superseded` → any | `TERMINAL_STATE` (terminal) |
| `planned` → `confirmed` | `ILLEGAL_TRANSITION` (must go through validation) |
| `previewed` → `committed` | `ILLEGAL_TRANSITION` (must go through `applied_to_branch`) |
| different scope | `SCOPE_MISMATCH` |
| turn_id mismatch | `SCOPE_MISMATCH` |
| operation_id collision (different scope/turn/type/fingerprint) | `OPERATION_COLLISION` |
| from_state mismatch (stale journal head) | `TRANSITION_STALE_FROM_STATE` |
| archived branch | `BRANCH_NOT_ACTIVE` |
| transition replay with different content | `TRANSITION_COLLISION` |
| `previewed` → `previewed` (same operation_id) | idempotent replay |
| `previewed` → `confirmed` (different operation_id) | `TRANSITION_COLLISION` |
| any state → `confirmed` without prior `previewed` | `ILLEGAL_TRANSITION` |
| `applied_to_branch` → `confirmed` (re-confirm) | `ILLEGAL_TRANSITION` |
| sequence != expected next sequence | `TRANSITION_SEQUENCE_COLLISION` |
| `previous_transition_id` != last transition id | `TRANSITION_PREVIOUS_MISMATCH` |
| `previous_transition_fingerprint` != last transition `record_fingerprint` | `TRANSITION_PREVIOUS_MISMATCH` |
| first transition (`sequence=0`) with non-null previous binding | `TRANSITION_PREVIOUS_MISMATCH` |
| non-first transition with null previous binding | `TRANSITION_PREVIOUS_MISMATCH` |
| journal replay: sequence gap or duplicate | `TRANSITION_SEQUENCE_COLLISION` |
| journal replay: previous binding chain broken | `TRANSITION_PREVIOUS_MISMATCH` |

## 4. Recovery and stale transitions

| Scenario | Detection | Recovery |
| --- | --- | --- |
| Source changed between plan and confirm | `context_fingerprint` mismatch | `TURN_SOURCE_CHANGED`; must re-plan |
| Timeline changed between plan and confirm | `timeline_id` mismatch on context | `TURN_TIMELINE_CHANGED`; must re-plan |
| Canon revision changed between plan and confirm | active canon != plan's `canon_revision` | `TURN_CANON_REVISION_CHANGED`; must re-plan |
| Branch archived between plan and confirm | `branch_id` status = `archived` | `BRANCH_NOT_ACTIVE`; must switch branch |
| Operation id collision (cross-branch / cross-timeline / cross-turn) | project-root authority record differs | `OPERATION_COLLISION` |
| Operation id replay (identical scope/turn/type/fingerprint) | project-root authority record matches | idempotent success (no write) |
| Partial write during confirm | immutable publication uses temp + fsync + `os.link` (create-if-absent) | retry with same `operation_id` → idempotent replay |
| Crash after Turn record written, before transition journal | on recovery, check Turn record exists but transition missing | re-append transition with same content → idempotent replay |
| Crash after transition written, before state delta | on recovery, transition journal exists; state delta is derivable | re-project state delta (deterministic from journal) |
| Journal sequence gap/duplicate on read | `get_transitions` validates contiguous sequence | `TRANSITION_SEQUENCE_COLLISION`; fail-closed |
| Journal previous binding broken on read | `get_transitions` validates `previous_transition_id` / `previous_transition_fingerprint` chain | `TRANSITION_PREVIOUS_MISMATCH`; fail-closed |
| Concurrent writers race same sequence slot | `_publish_immutable_json` atomic create-if-absent | first writer wins; second writer gets `TRANSITION_COLLISION` and must re-read journal |

## 5. Cancellation

- A Turn in `planned`/`awaiting_action`/`validating`/`requires_clarification`/`previewed` can be **abandoned** by the user simply not confirming it.
- Abandoned Turns are **not** persisted as confirmed records; they remain as plan records (read-only history) until superseded.
- A `confirmed` Turn **cannot** be cancelled; it is immutable.  To undo, the user must branch from the `parent_turn_id` and take a different action.
- A `committed` Turn **cannot** be undone except via the existing chapter rollback mechanism (out of Turn scope).
- **(FIX-RC)** A `blocked` Turn **cannot** be re-opened. To take a different action, the user must create a new Plan; the old Plan remains in the journal as terminal `blocked` history.

## 6. Superseded handling

A `planned` Turn becomes `superseded` when:

1. A new Turn plan is created for the same `chapter_id` + `branch_id` + `parent_turn_id` slot.
2. The source version changes (user selects a different source).
3. The canon revision changes (chapter was committed elsewhere).
4. The timeline/branch switches.

Superseded Turns are **terminal** and retained as read-only history.  They never enter chapter compilation.

**FIX-RC clarification:** When a branch switch happens, in-flight Plans
on the old branch enter `superseded` via the normal transition
machinery — they are **not** silently marked "abandoned". This keeps
the journal coherent and ensures the previous Plan is recoverable as
read-only history with a clear lifecycle end-state.

## 7. State persistence

**Design Pattern:** Immutable entity records + append-only transition journal.
Current state is derived from the transition journal; no in-place updates.
**(FIX-RC)** No `included_in_chapter` / `committed` flag is ever written
**on the Turn record itself** — those lifecycle facts live exclusively in
the transition journal.

| State | Persisted where | Immutable? |
| --- | --- | --- |
| `planned` | `data/narrative_turns/{timeline_id}/{branch_id}/plans/{turn_id}.json` | yes (create-if-absent publication) |
| `validating` | `data/narrative_turns/{timeline_id}/{branch_id}/validations/{validation_id}.json` | yes (create-if-absent publication) |
| `previewed` | transition journal entry | yes (append-only) |
| `confirmed` | `data/narrative_turns/{timeline_id}/{branch_id}/results/{turn_id}.json` | yes (create-if-absent publication) |
| `applied_to_branch` | transition journal entry | yes (append-only) |
| `included_in_chapter` | transition journal entry | yes (append-only) — **NOT a flag on the Turn record** |
| `committed` | transition journal entry | yes (append-only) — **NOT a flag on the Turn record** |

**Transition Journal (FIX-RC):**
- Path: `data/narrative_turns/{timeline_id}/{branch_id}/transitions/{turn_id}/{sequence:08d}.json`
- Filename is **sequence-only** (e.g. `00000000.json`, `00000001.json`).
  This forces concurrent writers racing the same next-sequence slot to
  collide on the same path, so atomic create-if-absent publication
  resolves first-wins deterministically.
- Each entry records `from_state`, `to_state`, `reason_code`,
  `operation_id`, `occurred_at` (audit only — not ordering key),
  `record_fingerprint`, `sequence`, `previous_transition_id`, and
  `previous_transition_fingerprint`.
- Current state derived by replaying transitions in **ascending
  `sequence` order**. `occurred_at` is not consulted for ordering.
- Chain integrity (`sequence` contiguous + `previous_transition_id` /
  `previous_transition_fingerprint` matching) is verified on **every
  read**; any break raises `TRANSITION_SEQUENCE_COLLISION` or
  `TRANSITION_PREVIOUS_MISMATCH` fail-closed.

**Operation Records (FIX-RC):**
- **Authoritative** (project-root): `data/narrative_turn_operations/{operation_id}.json`
- **Branch-local index** (rebuildable projection):
  `data/narrative_turns/{timeline_id}/{branch_id}/operations/{operation_id}.json`
- The authoritative record binds `operation_id` to
  `project_id` + `timeline_id` + `branch_id` + `turn_id` +
  `operation_type` + `payload_fingerprint`.
- Same `operation_id` + identical bindings → idempotent replay.
- Same `operation_id` + any differing binding → `OPERATION_COLLISION`.
- The authoritative record stores only a **relative**
  `result_record_path` — never an absolute filesystem path.

**Branch Lifecycle Events (FIX-RC2):**
- Path: `data/branches/{timeline_id}/lifecycle_events/{branch_id}/{sequence:08d}.json`
- Filename is **sequence-only** (e.g. `00000000.json`, `00000001.json`).
  `event_id` lives inside the JSON, not in the filename.
- Same pattern as transition journal: concurrent writes collide on the
  same sequence-named path; atomic create-if-absent resolves first-wins.
- Current lifecycle status derived by replaying events in ascending
  `sequence` order.

**Registry Events (FIX-RC2):**
- Path: `data/branches/{timeline_id}/registry_events/{sequence:08d}.json`
- Filename is **sequence-only**. `event_id` lives inside the JSON.
- The registry snapshot (`registry.json`) is a **mutable projection that
  can always be rebuilt deterministically from the event journal**
  by replaying events in ascending `sequence` order.
- Chain integrity (`sequence` contiguous + `previous_event_fingerprint`
  matching) is verified on every read; any break fails-closed.

**Branch Operations (FIX-RC2):**
- Multi-file operations (e.g. active archive with replacement) use a
  four-phase recoverable protocol tracked at project-root scope in
  `data/branch_operations/{operation_id}.json` (plus immutable phase
  markers `{operation_id}_registry_updated.json`,
  `{operation_id}_lifecycle_appended.json`, `{operation_id}_completed.json`).
- See Branch Isolation Map §2.3 for details.

## 8. Concurrency rules

- Only one `previewed` → `confirmed` transition per `turn_id` + `operation_id`.
- Duplicate `confirm` POST with same `operation_id` returns the original result (idempotent replay).
- Concurrent `confirm` with different `operation_id` for same `turn_id`: first wins, second gets `TRANSITION_COLLISION` (via the project-root operation authority record).
- **(FIX-RC)** Two concurrent appends targeting the same next
  `sequence` slot collide on the same sequence-named path
  (`{sequence:08d}.json`). `_publish_immutable_json` atomically resolves
  this: the first writer's `os.link` succeeds; the second writer's
  `os.link` hits `FileExistsError` and — because the content differs —
  surfaces `TRANSITION_COLLISION`. The losing writer must re-read the
  journal, observe the new head, and retry with the next sequence.
- **(FIX-RC)** `occurred_at` is **audit-only**. Two transitions with
  non-monotonic timestamps (e.g. clock skew across processes) do not
  affect state derivation, because ordering is by `sequence` alone.
- Branch-local event log uses append-only atomic write (same pattern as
  `ProviderUsageReconciliationStore`).
- Mutable projections (registry snapshot, optional transition head
  cache) may use `os.replace`, but they are **never** the authoritative
  record — they can always be rebuilt from the append-only journal.
- **(FIX-RC2)** Branch lifecycle events use the same sequence-only
  filename pattern and first-wins concurrency rule as turn transitions:
  concurrent appends to the same next `sequence` collide on the same
  path; atomic create-if-absent resolves first-wins deterministically.
- **(FIX-RC2)** Registry events also use sequence-only journal with
  first-wins concurrency. The `registry.json` snapshot is a mutable
  projection that can always be **rebuilt from the registry event
  journal** — it is never the authoritative record.
