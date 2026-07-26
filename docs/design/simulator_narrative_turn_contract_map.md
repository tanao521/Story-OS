# Simulator Narrative Turn — Contract Map

> Phase 0D4-A implementation artifact.  Contracts are **implemented** in
> `core/contracts/narrative_turn.py`.
>
> **Phase 0D4-A-FIX-RC** revises this map to match the implemented strict
> type discipline (no `list → tuple` conversion; list input is fail-closed),
> the separation between immutable branch identity and derived lifecycle
> projection, and the new transition sequence / operation authority fields.

**OWNER Decisions Applied:**
- `TimelineContext` is independent of `ProjectContext`
- `NarrativeScope` combines project_id + timeline_id + branch_id for all scope binding
- Branch `lifecycle_status` ("open"/"archived") separated from `active_branch_id` in registry
- Immutable records + append-only transition journal replaces in-place status updates
- Plan creation is a non-canonical write
- Validation scope fields completed
- **(FIX-RC)** Strict tuple input: `list` is rejected, not silently converted
- **(FIX-RC)** Branch identity record is immutable; lifecycle status is a derived projection
- **(FIX-RC)** Transitions are ordered by `sequence` with `previous_transition_id`/`previous_transition_fingerprint` binding
- **(FIX-RC)** Operation authority is project-root, not branch-local
- **(FIX-RC2)** Lifecycle event path改为 sequence-only
- **(FIX-RC2)** Registry event 确定性 sequence journal 可重建
- **(FIX-RC2)** Active archive 多文件操作可恢复
- **(FIX-RC2)** State delta 递归冻结

## 1. Authority objects (implemented)

### 1.1 NarrativeTurnPlan

```python
@dataclass(frozen=True)
class NarrativeTurnPlan:
    schema_version: str                    # "1.0"
    turn_id: str                           # deterministic id
    scope: NarrativeScope                  # project_id + timeline_id + branch_id
    chapter_id: int
    source_version_id: str | None
    parent_turn_id: str | None             # None for first turn in chapter
    context_fingerprint: str               # sha256 of bound context
    planning_revision: str                 # story_planning.json version
    canon_revision: str | None             # active canon revision at plan time
    created_at: str                        # ISO8601 UTC (with timezone)
    recommended_actions: tuple[NarrativeActionOption, ...]
    custom_action_policy: NarrativeCustomActionPolicy
```

**Binding rules:**
- `scope` MUST match the active context (project_id, timeline_id, branch_id).
- `chapter_id` + `source_version_id` MUST match the selected chapter source.
- `context_fingerprint` MUST be recomputed on every read; mismatch = `SCOPE_MISMATCH`.
- `parent_turn_id` forms a singly-linked chain within a branch.
- `parent_turn_id` cannot equal `turn_id`.
- `recommended_actions` is a **tuple of exactly 3** (deterministic).
- `deterministic_order` must be exactly 1, 2, 3.
- `action_id` must be unique within the plan.
- `intent` must be unique within the plan.
- **No `status` field** — lifecycle state tracked via append-only transition journal.

### 1.2 NarrativeActionOption

```python
@dataclass(frozen=True)
class NarrativeActionOption:
    action_id: str                         # deterministic, stable
    action_type: ActionType                # enum: advance|investigate|retreat|negotiate|sacrifice|custom_entry
    display_text: str                      # user-facing, no prompt injection
    intent: str                            # short deterministic description
    expected_costs: tuple[tuple[str, str], ...]   # qualitative: (("time","high"),("resource","medium"))
    expected_risks: tuple[tuple[str, str], ...]   # qualitative: (("relationship","low"),("safety","high"))
    required_conditions: tuple[str, ...]   # deterministic condition ids
    unavailable_reasons: tuple[str, ...]   # empty if available
    provenance: str                        # "deterministic-planner"
    deterministic_order: int               # 1, 2, 3
```

**Rules:**
- Exactly 3 options, `deterministic_order` 1/2/3.
- Unavailable options are **kept** with `unavailable_reasons` filled (not silently removed).
- `action_id` is stable: same context + same planning revision → same `action_id`.
- `display_text` is **never** passed to a provider; it is display-only.
- **(FIX-RC)** `expected_costs` and `expected_risks` are `tuple[tuple[str, str], ...]`.
  `list` input is **rejected** (fail-closed); `dict` input is **rejected**.
  There is no `list → tuple` conversion.

### 1.3 NarrativeCustomActionPolicy

```python
@dataclass(frozen=True)
class NarrativeCustomActionPolicy:
    max_length: int                        # e.g. 200
    forbidden_patterns: tuple[str, ...]    # regex, e.g. no prompt injection
    feasibility_pipeline: tuple[str, ...]  # ordered check names
```

### 1.4 NarrativeActionValidation

```python
@dataclass(frozen=True)
class NarrativeActionValidation:
    schema_version: str                    # "1.0"
    validation_id: str
    turn_id: str
    scope: NarrativeScope                  # project_id + timeline_id + branch_id
    chapter_id: int
    action_source: ActionSource            # "recommended"|"custom"
    selected_action_id: str | None         # required for recommended, forbidden for custom
    custom_action_text_hash: str | None    # required for custom, forbidden for recommended
    status: ValidationStatus               # "allowed"|"allowed_with_cost"|"requires_clarification"|"blocked"
    blocking_reasons: tuple[str, ...]      # deterministic reason codes
    cost_explanation: tuple[tuple[str, str], ...]  # qualitative
    risk_explanation: tuple[tuple[str, str], ...]  # qualitative
    checked_at: str                        # ISO8601 UTC (with timezone)
    context_fingerprint: str               # sha256 of bound context
```

**Rules:**
- `status` is one of the 4 explicit values; **no fuzzy "maybe"**.
- `selected_action_id` and `custom_action_text_hash` are mutually exclusive (XOR).
- `custom_action_text_hash` must be a valid SHA-256 hex string for custom actions.
- `context_fingerprint` binds validation to specific context; prevents replay.
- `cost_explanation` and `risk_explanation` are immutable tuples (not dicts).
- `blocking_reasons` uses structured codes from the error taxonomy.

### 1.5 NarrativeTurnResult

```python
@dataclass(frozen=True)
class NarrativeTurnResult:
    schema_version: str                    # "1.0"
    turn_id: str
    scope: NarrativeScope                  # project_id + timeline_id + branch_id
    chapter_id: int
    selected_action_id: str | None
    custom_action_text_hash: str | None
    result_status: ResultStatus            # "success"|"failure"|"partial"|"blocked"
    event_summary: str                     # short narrative summary (deterministic)
    state_delta_proposal: tuple[tuple[str, FrozenValue], ...]  # NarrativeMemoryService-compatible; recursive frozen
    consequence_flags: tuple[str, ...]     # e.g. ("relationship_worsened","resource_lost")
    next_context_fingerprint: str
    execution_revision: str                # branch-local event log revision
    source_fingerprint: str                # bound to source at confirm time
    confirmed_at: str                      # ISO8601 UTC (with timezone)
    operation_id: str                      # idempotency key
```

**Rules:**
- Immutable once written.
- `state_delta_proposal` is **branch-local**, never applied to global Canon.
- `state_delta_proposal` is stored as immutable tuple (not dict).
- **(FIX-RC2)** `state_delta_proposal` is recursively frozen: `tuple[tuple[str, FrozenValue], ...]`
  where `FrozenValue = str|int|float|bool|None|tuple[FrozenValue, ...]`.
  `dict` input is accepted at the boundary but immediately frozen into tuple-of-tuples
  (recursively for nested dicts/lists). The stored form is always deep-immutable.
- `source_fingerprint` MUST match the Turn plan's context; mismatch = `SCOPE_MISMATCH`.
- `operation_id` enables replay-safe confirmation and collision detection.
- Does NOT store: full Provider prompt, credentials, endpoints, absolute paths, raw exceptions.

### 1.6 Branch identity vs derived projection (FIX-RC)

The branch record is split into two layers as of Phase 0D4-A-FIX-RC:

#### 1.6.1 NarrativeBranchIdentity — immutable creation record

```python
@dataclass(frozen=True)
class NarrativeBranchIdentity:
    schema_version: str                    # "1.0"
    branch_id: str
    project_id: str
    timeline_id: str
    parent_branch_id: str | None           # None for root branch
    created_from_turn_id: str | None       # branch point
    display_name: str
    created_at: str                        # ISO8601 UTC (with timezone)
```

This record is published once via `_publish_immutable_json` and **never
overwritten**. It contains only identity fields. Lifecycle status is NOT
stored here.

#### 1.6.2 BranchLifecycleEvent — append-only lifecycle journal

```python
@dataclass(frozen=True)
class BranchLifecycleEvent:
    schema_version: str
    event_id: str
    sequence: int                          # 0, 1, 2, ...; contiguous
    branch_id: str
    project_id: str
    timeline_id: str
    from_status: BranchLifecycleStatus     # "open"|"archived"
    to_status: BranchLifecycleStatus       # "open"|"archived"
    operation_id: str | None
    occurred_at: str                       # ISO8601 UTC (audit only; not ordering key)
    previous_event_fingerprint: str | None # chain binding; None for sequence=0
    record_fingerprint: str                # sha256 of all fields except this one
```

Legal lifecycle transitions: `open → archived` and `archived → open`.
The current status is derived deterministically by replaying the event
journal (last event's `to_status`).

#### 1.6.3 NarrativeBranch — derived projection (read-only view)

```python
@dataclass(frozen=True)
class NarrativeBranch:
    schema_version: str                    # "1.0"
    branch_id: str
    project_id: str
    timeline_id: str
    parent_branch_id: str | None
    created_from_turn_id: str | None
    display_name: str
    lifecycle_status: BranchLifecycleStatus  # derived from event journal
    created_at: str                        # from immutable identity record
    archived_at: str | None                # derived: occurred_at of last ARCHIVED event
```

**Rules:**
- `lifecycle_status` is a **derived projection**, not a field on the
  immutable identity record.
- `lifecycle_status` is separate from `active_branch_id` in registry.
- Multiple open branches can exist per timeline.
- Only one `active_branch_id` per timeline registry.
- `active_branch_id` must point to an open branch.
- Archive of the active branch must specify an open replacement in the
  same atomic operation; partial failures must not leave `active_branch_id`
  pointing to an archived branch.
- `parent_branch_id` forms a tree; no cycles (parent cannot equal self).
- Root branch has `parent_branch_id: None`.
- `archived_at` is `None` when status is `open`; set to the last
  `ARCHIVED` event's `occurred_at` when status is `archived`.

### 1.7 NarrativeTurnTransition

```python
@dataclass(frozen=True)
class NarrativeTurnTransition:
    schema_version: str                    # "1.0"
    transition_id: str                     # deterministic id
    turn_id: str
    scope: NarrativeScope                  # project_id + timeline_id + branch_id
    from_state: TurnState                  # e.g. "planned", "validating"
    to_state: TurnState                    # e.g. "awaiting_action", "validated"
    reason_code: str                       # structured reason code
    operation_id: str | None               # idempotency key
    occurred_at: str                       # ISO8601 UTC (audit only; NOT ordering key)
    record_fingerprint: str                # sha256 of related record (Plan/Validation/Result)
    sequence: int                          # 0, 1, 2, ...; contiguous per turn (FIX-RC)
    previous_transition_id: str | None     # chain binding; None for sequence=0 (FIX-RC)
    previous_transition_fingerprint: str | None  # chain binding; None for sequence=0 (FIX-RC)
```

**Rules:**
- Legal transitions enforced by `_LEGAL_TRANSITIONS` frozenset.
- Terminal states (`blocked`, `committed`, `superseded`) cannot transition.
- `scope` must match the Turn's scope.
- `operation_id` enables idempotent replay.
- `record_fingerprint` binds transition to specific record version.
- **(FIX-RC)** Ordering is by `sequence`, NOT `occurred_at`. `occurred_at`
  is audit-only and may be non-monotonic without affecting state derivation.
- **(FIX-RC)** `sequence` must be contiguous per turn (0, 1, 2, …). Gaps
  or duplicates fail-closed on read.
- **(FIX-RC)** `previous_transition_id` and `previous_transition_fingerprint`
  must match the last appended transition. Mismatch fails-closed.
- **(FIX-RC)** The first transition (`sequence=0`) must have
  `previous_transition_id=None` and `previous_transition_fingerprint=None`.
- **(FIX-RC)** Concurrent writes to the same sequence slot use atomic
  create-if-absent publication (`os.link`); only one writer wins, others
  must re-read and retry.

**Legal Transitions:**
- `planned` → `awaiting_action`
- `planned` → `superseded`
- `awaiting_action` → `validating`
- `validating` → `validated`
- `validating` → `blocked`
- `validating` → `requires_clarification`
- `requires_clarification` → `awaiting_action`
- `validated` → `previewed`
- `previewed` → `confirmed`
- `confirmed` → `applied_to_branch`
- `applied_to_branch` → `included_in_chapter`
- `included_in_chapter` → `committed`

### 1.8 RegistryEvent (FIX-RC2)

```python
@dataclass(frozen=True)
class RegistryEvent:
    schema_version: str
    event_id: str
    sequence: int                          # 0, 1, 2, ...; contiguous per timeline
    project_id: str
    timeline_id: str
    event_type: str                        # "branch_created"|"branch_selected"|"branch_archived"
    from_active_branch_id: str | None      # active pointer before this event
    to_active_branch_id: str | None        # active pointer after this event
    expected_revision: str                 # CAS revision read before applying
    resulting_revision: str                # CAS revision written after applying
    operation_id: str | None               # bound branch operation, if any
    occurred_at: str                       # ISO8601 UTC (audit only; not ordering key)
    previous_event_id: str | None          # chain binding; None for sequence=0
    previous_event_fingerprint: str | None # chain binding; None for sequence=0
    record_fingerprint: str                # sha256 of all fields except this one
```

**Rules:**
- **(FIX-RC2 — Scheme A: explicit fields, NOT generic payload.)** The
  registry snapshot is rebuilt from `from_active_branch_id` /
  `to_active_branch_id` / `expected_revision` / `resulting_revision`
  carried as **first-class fields on every event**. Reconstruction
  never relies on optional or unvalidated dictionary keys inside a
  generic `payload`.
- **(FIX-RC2)** Registry events are stored in a deterministic sequence journal
  at `data/branches/{timeline_id}/registry_events/{sequence:08d}.json`.
  Filename is sequence-only; `event_id` lives inside the JSON.
- **(FIX-RC2)** The registry snapshot (`registry.json`) is a mutable projection
  that can always be **rebuilt deterministically from the event journal
  by replaying events in ascending `sequence` order**, taking the last
  event's `to_active_branch_id` as `active_branch_id` and the last
  event's `resulting_revision` as `revision`.
- `sequence` must be contiguous per timeline (0, 1, 2, …). Gaps or
  duplicates fail-closed on read.
- `previous_event_id` and `previous_event_fingerprint` must match the
  last appended event. Mismatch fails-closed.
- Concurrent writes to the same sequence slot use atomic create-if-absent
  publication; only one writer wins, others must re-read and retry.
- The first event (`sequence=0`) must have `previous_event_id=None` and
  `previous_event_fingerprint=None`.

### 1.9 BranchOperationRecord (FIX-RC2)

```python
class BranchOperationPhase(str, Enum):
    INTENT = "intent"
    REGISTRY_UPDATED = "registry_updated"
    LIFECYCLE_APPENDED = "lifecycle_appended"
    COMPLETED = "completed"

@dataclass(frozen=True)
class BranchOperationRecord:
    schema_version: str
    operation_id: str
    project_id: str
    timeline_id: str
    operation_type: BranchOperationType  # "active_archive_with_replacement"
    target_branch_id: str                # branch being archived
    replacement_branch_id: str           # branch to activate
    expected_registry_revision: str      # CAS revision read at phase=intent
    initial_target_status: BranchLifecycleStatus  # "open"|"archived"
    phase: BranchOperationPhase  # "intent"|"registry_updated"|"lifecycle_appended"|"completed"
    resulting_registry_revision: str | None       # set at phase >= registry_updated
    lifecycle_event_fingerprint: str | None       # set at phase >= lifecycle_appended
    payload_fingerprint: str
    created_at: str                       # ISO8601 UTC (with timezone)
    record_fingerprint: str               # sha256 of all fields except this one
```

**Rules:**
- **(FIX-RC2)** Multi-file branch operations (e.g. active archive with
  replacement) use a four-phase recoverable protocol.
  The operation record tracks progress so that a crash mid-operation
  can be detected and resumed or rolled back.
- **Phases (REGISTRY-FIRST safe order):**
  1. `intent` — operation record published with phase=`intent`; no side effects yet
  2. `registry_updated` — registry CAS active pointer → replacement;
     `_append_registry_event(event_type="branch_archived", from=target, to=replacement)`;
     immutable `{operation_id}_registry_updated.json` marker published
  3. `lifecycle_appended` — if target not already archived,
     `_append_lifecycle_event(target, OPEN → ARCHIVED)`;
     immutable `{operation_id}_lifecycle_appended.json` marker published
  4. `completed` — immutable `{operation_id}_completed.json` marker published
- On recovery, if an operation is found not in `completed` phase,
  the store inspects which immutable phase markers already exist on
  disk and resumes from the next incomplete phase. All phases are idempotent.
- **Safe invariant:** `active_branch_id` never points to an archived
  branch in any observable or recoverable state — the REGISTRY-FIRST
  order flips the active pointer to the open replacement *before*
  archiving the target.
- Operation records are stored at **project-root scope** (not
  timeline-isolated), alongside their immutable phase markers:
  - `data/branch_operations/{operation_id}.json` — main operation record (mutable projection)
  - `data/branch_operations/{operation_id}_registry_updated.json` — immutable phase marker
  - `data/branch_operations/{operation_id}_lifecycle_appended.json` — immutable phase marker
  - `data/branch_operations/{operation_id}_completed.json` — immutable phase marker

## 2. What is NOT added

- **No** `NarrativeTurnRun` — a Turn is not a "run"; it is a confirmed record.  The "run" concept stays with Panel Run.
- **No** `NarrativeStateDelta` as a separate object — it is a field on `NarrativeTurnResult`, shaped to match `NarrativeMemoryService` event records.
- **No** `NarrativeScene` — scene-level compilation is a future concern; 0D4 operates at Turn granularity.

## 3. What IS added (0D4-A)

- `TimelineContext` — independent of `ProjectContext`
- `NarrativeScope` — combines project_id + timeline_id + branch_id
- `NarrativeTurnTransition` — append-only lifecycle transition journal

## 4. Field binding matrix

| Field | Required on Plan | Required on Validation | Required on Result | Notes |
| --- | --- | --- | --- | --- |
| `schema_version` | yes | yes | yes | "1.0"; unknown version fails |
| `turn_id` | yes | yes | yes | deterministic, immutable |
| `scope` | yes | yes | yes | project_id + timeline_id + branch_id |
| `chapter_id` | yes | yes | yes | must match selected chapter |
| `source_version_id` | yes (or None) | no | no | bound at plan time |
| `parent_turn_id` | yes (or None) | no | no | chain within branch; cannot equal turn_id |
| `context_fingerprint` | yes | yes | no | prevents cross-scope replay |
| `canon_revision` | yes (or None) | no | no | active canon at plan time |
| `source_fingerprint` | no | no | yes | bound at confirm time |
| `operation_id` | no | no | yes | idempotency key |
| `selected_action_id` | no | yes (for recommended) | yes (or None) | XOR with custom_action_text_hash |
| `custom_action_text_hash` | no | yes (for custom) | yes (or None) | XOR with selected_action_id; SHA-256 required |

## 5. Strict type discipline (FIX-RC)

Phase 0D4-A-FIX-RC enforces fail-closed input types. There is **no**
`list → tuple` or `dict → tuple[tuple[str, str], ...]` conversion.

| Field type | Accepted input | Rejected input (fail-closed) |
| --- | --- | --- |
| `tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `tuple[tuple[str, str], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `int` | `int` (type(value) is int) | `bool`, `float`, `str` |
| `enum` | enum instance | `str` (must use the enum constructor), unknown values |
| `datetime` | `str` ISO8601 with timezone | timezone-naive strings, non-ISO strings |

**Runtime validators:**
- `_require_tuple(value, field_name)` — rejects `list`, `dict`, and other types.
- `_require_tuple_of_tuples(value, field_name)` — rejects `list`, `dict`,
  and non-tuple types.
- `_validate_int(value, field_name, allow_zero=False)` — uses
  `type(value) is int` so `bool` (a subclass of `int`) is rejected.

**No silent conversion:** callers must pass the correct immutable type.
This prevents accidental mutability through nested mutable objects.

## 6. Common validation rules

All contracts enforce:
- `@dataclass(frozen=True)` — immutable after creation
- `schema_version` required and validated
- Unknown schema version → fail-closed
- Empty strings rejected
- ID patterns: `^[A-Za-z0-9_-]+$`
- Hash patterns: `^[0-9a-f]{64}$` (SHA-256)
- Timezone-naive datetime rejected
- Enum values validated (unknown values rejected)
- Internal exceptions wrapped in `NarrativeTurnError`

## 7. What must NOT be stored

- Full provider prompt or response text.
- Credentials, API keys, endpoints.
- Absolute filesystem paths (only project-relative).
- Raw internal exceptions.
- Reader Persona free-text feedback (that lives in panel run store, not Turn store).
- Model supplement text (that lives in panel run store).

## 8. Operation authority (FIX-RC)

Operation identifiers are tracked at **project-root** authority to detect
cross-branch / cross-timeline / cross-turn collisions:

```
data/narrative_turn_operations/{operation_id}.json   # authoritative
data/narrative_turns/{timeline_id}/{branch_id}/operations/{operation_id}.json  # branch-local index
data/branch_operations/{operation_id}.json  # branch lifecycle operations (FIX-RC2; project-root scope, not timeline-isolated)
```

**Authority record fields:**
- `operation_id`
- `project_id`
- `timeline_id`
- `branch_id`
- `turn_id`
- `operation_type` (e.g. "plan", "validation", "result", "transition")
- `payload_fingerprint` (sha256 of the bound record)
- `result_record_path` (project-relative, never absolute)
- `created_at`

**Collision rules:**
- Same `operation_id` + identical scope/turn/type/fingerprint → idempotent replay.
- Same `operation_id` + different `branch_id` → `OPERATION_COLLISION`.
- Same `operation_id` + different `timeline_id` → `OPERATION_COLLISION`.
- Same `operation_id` + different `turn_id` → `OPERATION_COLLISION`.
- Same `operation_id` + different `payload_fingerprint` → `OPERATION_COLLISION`.
- Authority records use `_publish_immutable_json` (atomic create-if-absent).
- The branch-local index is a mutable-derived projection (rebuildable from
  authority); it stores only relative paths.
- Project isolation is provided by `ProjectContext` root; `project_id` is
  still stored on the record and verified on read.
