# Phase 0D4-B — Deterministic Narrative Turn Planner, Action Feasibility & Read-Only Preview

> Status: **SEALED**
>
> Phase 0D4-P: PASSED
> Phase 0D4-A: SEALED
> Phase 0D4-B-FIX-RC: ACCEPTED
> Phase 0D4-B-FIX-RC-FV: PASSED
> Phase 0D4-B: SEALED
> Phase 0D4-C: NOT ENTERED
> Phase 0D4-D: NOT ENTERED
> Phase 0D4-E: NOT ENTERED
> Phase 0D4-F: NOT ENTERED

## 1. Phase Overview

Phase 0D4-B implements the deterministic, read-only planning layer for
Narrative Turn:

1. **Context Binder** — pure read-only context snapshot with deterministic
   fingerprint (cold-start safe, no writes)
2. **Deterministic Planner** — generates exactly 3 recommended actions
   from structured evidence
3. **Action Feasibility Engine** — 14-step validation pipeline with 4
   status classifications
4. **Read-Only Preview** — qualitative consequence projection, no
   persistent side effects

**Strict Boundary (0D4-B does NOT):**
- ❌ Confirm turns
- ❌ Persist turn lifecycle state
- ❌ Write branch events
- ❌ Write Canon
- ❌ Modify UI
- ❌ Call Provider
- ❌ Access network
- ❌ Use randomness
- ❌ Create/modify/repair any file during `bind()` (cold-start read-only)

## 2. Implementation Files

### 2.1 New files

| File | Purpose |
| --- | --- |
| `system/narrative_turn_context.py` | Context Binder + deep-immutable snapshot + strict canonical fingerprint |
| `system/narrative_turn_planner.py` | Deterministic Planner (3 recommended actions) |
| `system/narrative_action_feasibility.py` | Feasibility Engine (14-step pipeline) |
| `system/narrative_turn_preview.py` | Read-only Preview service |
| `core/contracts/narrative_turn_preview.py` | Preview DTO + fingerprint function |
| `tests/test_phase0d4b_narrative_turn_planner.py` | 124 focused tests (85 original + 26 FIX-RC + 13 FIX-RC-FV) |

### 2.2 Design docs

| File | Purpose |
| --- | --- |
| `docs/design/simulator_narrative_turn_planner.md` | Planner design doc |
| `docs/design/simulator_action_feasibility.md` | Feasibility engine design doc |

## 3. Context Binder

### 3.1 Cold-start read-only guarantee

`bind()` never creates, modifies, or repairs any file. All loader calls
use read-only paths that return structured missing/error on absent data
rather than auto-initializing.

**Forbidden behaviors (all verified absent by `TestColdStartReadOnly`):**
- Creating planning files
- Auto-supplementing chapter IDs
- Creating initial Canon
- Creating revisions
- Creating branch registry
- Initializing NarrativeMemory
- Writing backups
- Modifying source selection
- Writing caches
- Creating directories
- Repairing corrupted data
- Calling any `ensure`/`create`/`init`/`repair` method

**Read-only entry points used:**
- `_read_json_file(path)` — returns `None` on missing/invalid, never writes
- `_read_text_file(path)` — returns `None` on missing, never writes
- `_read_planning_raw()` — reads `story_planning.json` directly (no `_normalize`)
- `_read_canon_revision(chapter_id)` — reads `canon_versions/chapter_NNN/index.json` directly (no `RevisionService.active_canon`)
- `_read_source(chapter_id)` — reads `versions/chapter_NNN_versions.json` directly (no `load_versions_index`)
- `_read_branch_info(timeline_ctx, branch_id)` — reads branch + registry from journal events (no `_create_registry_if_missing`)
- `_read_branch_state(timeline_ctx, branch_id)` — reads branch-scoped state only

### 3.2 Snapshot fields

`NarrativeTurnContextSnapshot` (frozen dataclass with deep immutability) includes:

| Field | Type | Authority |
| --- | --- | --- |
| `schema_version` | `str` | Always "1.0" |
| `scope` | `NarrativeScope` | project_id + timeline_id + branch_id |
| `chapter_id` | `int` | Numeric chapter number |
| `source_version_id` | `str \| None` | Selected source version |
| `source_fingerprint` | `str` | SHA-256 of chapter source content |
| `canon_revision` | `str \| None` | Active Canon revision ID |
| `planning_revision` | `str` | SHA-256 of planning data |
| `chapter_plan_revision` | `str \| None` | SHA-256 of chapter plan |
| `dependency_revision` | `str \| None` | SHA-256 of planning dependencies |
| `branch_state_revision` | `str \| None` | SHA-256 of branch-scoped state |
| `world_revision` | `str \| None` | World bible fingerprint |
| `character_revision` | `str \| None` | Characters fingerprint |
| `location_revision` | `str \| None` | Locations fingerprint |
| `resource_revision` | `str \| None` | Resources fingerprint |
| `relationship_revision` | `str \| None` | Relationships fingerprint |
| `time_state_revision` | `str \| None` | Rolling window / time state fingerprint |
| `planner_revision` | `str` | Planner version string |
| `context_fingerprint` | `str` | Combined deterministic fingerprint |
| `branch_open` | `bool` | Branch lifecycle is "open" |
| `branch_is_active` | `bool` | Branch is currently selected |
| `planning_data` | `tuple` (frozen) | Full planning data (deep-immutable) |
| `chapter_plan` | `tuple` (frozen) | Chapter plan (deep-immutable) |
| `world_data` | `tuple` (frozen) | World bible data (deep-immutable) |
| `character_data` | `tuple` (frozen) | Character data (deep-immutable) |
| `narrative_state` | `tuple` (frozen) | Branch state (deep-immutable) |
| `rolling_window` | `tuple` (frozen) | Rolling window (deep-immutable) |
| `dependencies` | `tuple` (frozen) | Dependencies (deep-immutable) |
| `evidence_codes` | `tuple[str, ...]` | Evidence codes for what was bound |
| `limitations` | `tuple[str, ...]` | Missing / advisory data notes |

**Deep immutability:** All dict/list fields are recursively frozen at
construction time via `_freeze()`. Dicts become sorted tuples of
`(str, frozen_value)` pairs; lists become tuples. Mutation of the
original input data after `bind()` has no effect on the snapshot or its
fingerprint. Accessor methods (`planning_data_dict()`, etc.) return
fresh deep copies via `_unfreeze()`.

### 3.3 Fingerprint generation (complete authority inputs)

`context_fingerprint` is SHA-256 of strict canonical JSON (no `default=str`)
containing all authority inputs:

```
planner_revision
project_id
timeline_id
branch_id
chapter_id
source_version_id
source_fingerprint
canon_revision
planning_revision
chapter_plan_revision
dependency_revision
branch_state_revision
world_revision
character_revision
location_revision
resource_revision
relationship_revision
time_state_revision
```

If multiple data items come from the same file, they share a revision
but each is listed explicitly. Advisory data that does not influence
Planner, Feasibility, or Preview output is excluded; once any component
reads it and changes output, it must enter the fingerprint.

### 3.4 Strict canonical serialization

Fingerprint computation uses `_canonical_json()` which:
- **Allows:** `null`, `bool`, strict `int`, finite `float`, `str`, frozen sequence, frozen object
- **Rejects:** `NaN`, `Infinity`, `Path`, `datetime` (unless pre-converted to ISO8601), `set`, `bytes`, custom objects
- Object keys must be strings; keys are sorted
- Fixed separators `(",", ":")`; fixed Unicode policy (`ensure_ascii=False`)
- Does NOT read locale
- Does NOT use Python `hash()`
- Does NOT use `default=str` fallback
- Unknown values raise `ContextValueInvalid` (structured `CONTEXT_VALUE_INVALID`)

The fingerprint does NOT use:
- File mtime
- Absolute paths
- Current time
- Random numbers
- Python `hash()`
- Memory addresses

### 3.5 Branch state isolation

The binder reads ONLY the branch-scoped state path:

```
data/narrative_memory/state/{timeline_id}/{branch_id}/current.json
```

The legacy flat path `data/narrative_memory/state/current.json` is
NEVER read as branch-local authority.

**Behavior:**
- **Branch-scoped state exists & scope matches:** returns revision + data
- **Branch-scoped state missing:** returns `branch_state_revision=None`,
  `limitation=BRANCH_STATE_UNAVAILABLE`
- **Scope mismatch (project/timeline/branch):** returns `None`,
  `limitation=BRANCH_STATE_{PROJECT,TIMELINE,BRANCH}_MISMATCH`
- Never falls back to other branches, main branch, or project-flat state

### 3.6 Fail-closed error codes

| Code | Trigger |
| --- | --- |
| `TURN_CONTEXT_NOT_READY` | General context binding failure |
| `TURN_SOURCE_MISSING` | Chapter source file not found |
| `TURN_SOURCE_CHANGED` | Source fingerprint mismatch (stale check) |
| `TURN_CANON_REVISION_CHANGED` | Canon revision mismatch |
| `TURN_TIMELINE_CHANGED` | Timeline mismatch |
| `BRANCH_NOT_FOUND` | Branch does not exist |
| `BRANCH_NOT_ACTIVE` | Branch is not selected |
| `BRANCH_ARCHIVED` | Branch lifecycle is archived |
| `PLANNING_DATA_MISSING` | story_planning.json not found |
| `PLANNING_DATA_INVALID` | Planning data parse error |
| `WORLD_DATA_INVALID` | World bible parse error |
| `CHARACTER_DATA_INVALID` | Character data parse error |
| `CONTEXT_VALUE_INVALID` | Non-canonical value type in fingerprint input |
| `BRANCH_STATE_UNAVAILABLE` | Branch-scoped state file missing |
| `BRANCH_STATE_PROJECT_MISMATCH` | State record project_id mismatch |
| `BRANCH_STATE_TIMELINE_MISMATCH` | State record timeline_id mismatch |
| `BRANCH_STATE_BRANCH_MISMATCH` | State record branch_id mismatch |

## 4. Deterministic Planner

### 4.1 Planner revision

```
planner_revision = "narrative-turn-planner-v1"
```

### 4.2 Candidate generation

Candidates come from 8 categories, each requiring at least one
structured evidence source:

1. Advance current goal (chapter goal + plot threads)
2. Investigate unknown (unresolved threads + locations)
3. Mitigate risk (conflicts + world constraints)
4. Protect resources (inventory + character status)
5. Negotiate / relationship (character relationships)
6. Retreat / wait (time constraints + safety)
7. High-cost breakthrough (resource trade-offs)
8. Sacrifice for progress (resource + relationship capital)

### 4.3 Scoring

Deterministic integer score from goal relevance, urgency, evidence
support, conflict differentiation, capability compatibility, minus
unavailable and duplication penalties.

### 4.4 Exactly-3 guarantee

- Always exactly 3 `recommended_actions`
- `deterministic_order` = 1, 2, 3
- Unique `action_id`, unique `intent`
- At least 2 different `action_type` values
- Semantic categories differ

If evidence is insufficient, fill with conservative options marked
`unavailable_reasons: ["CONTEXT_INSUFFICIENT"]`.

### 4.5 Action ID

```
action_id = sha256(
    planner_revision : context_fingerprint :
    normalized_intent : action_type : deterministic_order
)[:16]
```

## 5. Action Feasibility Engine

### 5.1 Pipeline order (14 steps)

1. Input validation
2. Context / scope binding
3. Source and revision freshness
4. Branch status
5. Action structure extraction
6. World-rule check
7. Canon conflict check
8. Character capability check
9. Resource check
10. Location check
11. Time-window check
12. Relationship / permission check
13. Dependency check
14. Cost / risk classification

Short-circuits on first `blocked`.

### 5.2 Status hierarchy

```
blocked > requires_clarification > allowed_with_cost > allowed
```

### 5.3 Custom action normalization

`normalize_custom_action(text)`:
- Unicode NFKC
- Strip + collapse whitespace
- Reject NUL / control characters
- Length limit (200 chars)
- Returns `NormalizedCustomAction` with `text_hash` (SHA-256)

Only the hash persists; full text is ephemeral.

## 6. Read-Only Preview

### 6.1 Output DTO

`NarrativeTurnPreview` contains:

| Field | Purpose |
| --- | --- |
| `preview_fingerprint` | Deterministic fingerprint of inputs |
| `context_fingerprint` | Context that was previewed |
| `action_source` | "recommended" or "custom" |
| `action_id` | Recommended action ID (or "custom") |
| `custom_action_text_hash` | Hash of normalized custom text |
| `validation_status` | Feasibility status |
| `reason_codes` | Structured reason codes |
| `expected_costs` | List of qualitative cost descriptions |
| `expected_risks` | List of qualitative risk descriptions |
| `likely_consequences` | List of qualitative consequence descriptions |
| `evidence_codes` | Evidence supporting the prediction |
| `limitations` | What the preview cannot predict |
| `checked_at` | Clock injection timestamp |

### 6.2 Preview rules

- **No writes**: never creates Result, Transition, branch event, or
  state delta
- **Qualitative only**: no numeric probabilities, no generated text
- **No canonical language**: consequences use "may", "could", "likely"
  — never "will" or "has happened"
- **Limitations explicit**: always lists what is not predictable
- **Deterministic**: same inputs → same `preview_fingerprint`

## 7. Test Summary

- **124** focused tests in `test_phase0d4b_narrative_turn_planner.py`
  (85 original + 26 FIX-RC + 13 FIX-RC-FV)
- **138** 0D4-A regression tests (all pass)
- **76** non-0D4-A regression tests across 9 suites (all pass, 3 warnings)
- `compileall` passes
- AST parse passes (7 files)
- Runtime imports succeed

### 7.1 Focused test categories

| Category | Count |
| --- | --- |
| Context binding (TestContextBinder) | 16 |
| Deterministic planner (TestDeterministicPlanner) | 17 |
| Recommended feasibility (TestRecommendedFeasibility) | 6 |
| Custom action normalization (TestCustomActionNormalization) | 14 |
| Custom action feasibility (TestCustomActionFeasibility) | 10 |
| Read-only preview (TestReadOnlyPreview) | 9 |
| Security boundaries (TestSecurityBoundaries) | 8 |
| Integration read-only flow (TestIntegrationReadOnlyFlow) | 5 |
| **Original 0D4-B subtotal** | **85** |
| Cold-start read-only (TestColdStartReadOnly, FIX-RC) | 6 |
| Deep immutability (TestDeepImmutability, FIX-RC) | 5 |
| Strict canonical serialization (TestStrictCanonicalSerialization, FIX-RC) | 7 |
| Branch state isolation (TestBranchStateIsolation, FIX-RC) | 4 |
| Complete fingerprint (TestCompleteFingerprint, FIX-RC) | 4 |
| **FIX-RC subtotal** | **26** |
| Branch-state path lock (TestFactLockBranchStatePath, FV) | 2 |
| Custom action length lock (TestFactLockCustomActionLength, FV) | 6 |
| Missing vs invalid lock (TestFactLockMissingVsInvalid, FV) | 4 |
| Test count lock (TestFactLockTestCount, FV) | 1 |
| **FIX-RC-FV subtotal** | **13** |
| **Total** | **124** |

### 7.2 Regression suite counts

| Suite | Count | Result |
| --- | --- | --- |
| 0D4-A foundation | 138 | 138 passed |
| ProjectContext isolation | 15 | 15 passed |
| Vector isolation | 28 | 28 passed |
| Static path guard | 3 | 3 passed |
| Planning rolling window | 5 | 5 passed, 1 warning |
| Planning control | 3 | 3 passed, 1 warning |
| Version manager | 8 | 8 passed |
| Revision service | 4 | 4 passed |
| Commit selected version | 3 | 3 passed |
| Planning dependencies | 7 | 7 passed, 1 warning |
| **Non-0D4-A regression total** | **76** | **76 passed, 3 warnings** |

### 7.3 Static checks

| Check | Result |
| --- | --- |
| `python -m compileall` (6 source files) | Passed (exit 0) |
| AST parse (7 files) | Passed |
| Runtime imports of all 0D4-B modules | Passed |
| Cold-start filesystem no-diff | Passed (TestColdStartReadOnly: 6 tests) |
| No absolute paths in output | Passed (security test) |
| No raw exception leak | Passed (security test) |

## 8. Security Boundaries

| Boundary | Status |
| --- | --- |
| Provider calls | 0 |
| Network calls | 0 |
| Real tokens / cost | 0 |
| Canon writes | 0 |
| Chroma writes | 0 |
| NarrativeMemory writes | 0 |
| Branch lifecycle writes | 0 (bind is read-only; no subsystem init triggered) |
| NarrativeTurnStore writes | 0 (append_plan never called) |
| Production UI changes | 0 |
| HTTP route changes | 0 |
| New dependencies | 0 |
| Git write operations | 0 |

## 9. Phase 0D4-B-FIX-RC Closure

The following 6 issues identified in the PARTIALLY PASSED verdict are
now closed:

1. ✅ **Context Binder cold-start writes** — `bind()` uses read-only
   paths only; verified by `TestColdStartReadOnly` (6 tests)
2. ✅ **Incomplete context fingerprint** — all 18 authority inputs
   contribute to fingerprint; verified by `TestCompleteFingerprint`
   (4 tests)
3. ✅ **Context Snapshot deep mutability** — recursive `_freeze()`
   converts all dicts/lists to immutable tuples; verified by
   `TestDeepImmutability` (5 tests)
4. ✅ **`default=str` non-strict serialization** — replaced with
   `_canonicalize()` that rejects non-canonical types; verified by
   `TestStrictCanonicalSerialization` (7 tests)
5. ✅ **Branch state legacy path pollution** — only branch-scoped path
   is read; verified by `TestBranchStateIsolation` (4 tests)
6. ✅ **Documentation/test count inconsistency** — all documents now
   reflect 124 focused tests and accurate per-suite regression counts

## 9.1 Phase 0D4-B-FIX-RC-FV Closure

The following 4 fact-verification issues were locked by FV tests:

1. ✅ **Branch-state path authority** — only
   `data/narrative_memory/state/{timeline_id}/{branch_id}/current.json`
   is read; legacy flat path is never used as authority; verified by
   `TestFactLockBranchStatePath` (2 tests)
2. ✅ **Custom action length single source of truth** —
   `MAX_CUSTOM_ACTION_LENGTH == 200`, matching
   `NarrativeCustomActionPolicy.max_length == 200`, normalization
   boundary, and design docs; verified by
   `TestFactLockCustomActionLength` (6 tests)
3. ✅ **Missing vs invalid distinction** — absent files yield
   `*_MISSING` limitations; malformed JSON or wrong-top-level-type
   files yield `*_INVALID` limitations; verified by
   `TestFactLockMissingVsInvalid` (4 tests)
4. ✅ **Test-count self-verification** — documented focused test total
   matches `pytest --collect-only` output; verified by
   `TestFactLockTestCount` (1 test)

## 10. What's Next (0D4-C / 0D4-D)

- **0D4-C**: UI integration (NOT ENTERED — not authorized from 0D4-B)
- **0D4-D**: Persistence and state machine transitions (append_plan,
  append_validation, confirm, etc.)
- **0D4-E**: HTTP API endpoints
- **0D4-F**: Chapter compilation and Canon commit
