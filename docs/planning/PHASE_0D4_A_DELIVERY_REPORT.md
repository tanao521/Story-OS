# Phase 0D4-A Delivery Report

> ```text
> HISTORICAL INITIAL DELIVERY
> SUPERSEDED BY PHASE_0D4-A-FIX-RC2
> NOT AUTHORITATIVE FOR CURRENT IMPLEMENTATION
> ```
>
> Status (historical): **PASSED**
> Date: 2026-07-24
>
> **重要：** 本报告为 Phase 0D4-A 的**初始**交付报告，仅作为历史证据保留。
> 当前权威实现以 `PHASE_0D4_A.md`（FIX-RC2-FV 版本）和
> `PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md` 为准。
>
> 以下初始报告中的描述**已被 FIX-RC2 替代**，**不得**作为当前实现依据：
> - ❌ `os.replace` 用于 immutable 写入 → 真实代码使用 `_publish_immutable_json`
>   + `os.link`（create-if-absent），`os.replace` 仅用于 mutable 投影
> - ❌ `list → tuple` 转换 → 真实代码采用严格 fail-closed 策略，拒绝 `list` 输入
> - ❌ transition 文件名为 `{transition_id}.json` → 真实代码为 `{sequence:08d}.json`
> - ❌ registry event 文件名为 `{event_id}.json` → 真实代码为 `{sequence:08d}.json`
> - ❌ mutable branch lifecycle（直接覆写 branch record）→ 真实代码使用
>   append-only lifecycle event journal + 派生投影
> - ❌ 46 passed → 真实代码 132 + 6 fact-locking = 138 passed
>
> 以下章节中保留的原测试数量和原实现事实仅作为初始交付时的历史证据。
> 详情参见 `PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md`。

---

## 1. Phase Conclusion

Phase 0D4-A has been successfully implemented and verified. All OWNER decisions have been applied, all focused tests pass, and no security-critical violations were detected.

**Final State:**
- Phase 0D4-A: **PASSED**
- Narrative Turn foundation: **IMPLEMENTED**
- Production Narrative Turn flow: **NOT STARTED**
- Phase 0D4-B: **NOT ENTERED**

---

## 2. Baseline Before Start

**Git Root:** `d:\novel\StoryOS`

**Git Status:**
- Branch: `agent/phase-13-2-memory-repair`
- 2 commits ahead of origin
- Existing modifications tracked (unrelated to 0D4-A)

**Existing Files:**
- No pre-existing `narrative_turn.py`, `narrative_turn_store.py`, or `narrative_branch_store.py`
- Design documents existed as 0D4-P artifacts

**Test Baseline:**
- None (first implementation)

---

## 3. OWNER Decision Implementation Matrix

| Decision | Status | Implementation |
| --- | --- | --- |
| `TimelineContext` independent of `ProjectContext` | ✅ | `core/contracts/narrative_turn.py:TimelineContext` |
| `NarrativeScope` combines project_id + timeline_id + branch_id | ✅ | `core/contracts/narrative_turn.py:NarrativeScope` |
| Branch `lifecycle_status` ("open"/"archived") separated from `active_branch_id` | ✅ | `NarrativeBranch.lifecycle_status` + registry `active_branch_id` |
| Immutable records + append-only transition journal | ✅ | `NarrativeTurnTransition` + transition journal store |
| Plan creation is a non-canonical write | ✅ | Plan appended via `append_plan()` |
| Validation scope fields completed | ✅ | `NarrativeActionValidation` includes full scope |

---

## 4. Contract List

### 4.1 Contexts
- `TimelineContext` — `project_id`, `timeline_id`
- `NarrativeScope` — `project_id`, `timeline_id`, `branch_id`

### 4.2 Core Contracts
- `NarrativeTurnPlan` — Immutable Turn plan
- `NarrativeActionOption` — Recommended action
- `NarrativeCustomActionPolicy` — Custom action constraints
- `NarrativeActionValidation` — Action validation result
- `NarrativeTurnResult` — Confirmed Turn result
- `NarrativeBranch` — Branch entity
- `NarrativeTurnTransition` — Lifecycle transition

### 4.3 Enums
- `TurnState` — 12 states (planned → committed)
- `ActionType` — 6 types (advance, investigate, retreat, negotiate, sacrifice, custom_entry)
- `ActionSource` — recommended, custom
- `ValidationStatus` — allowed, allowed_with_cost, requires_clarification, blocked
- `ResultStatus` — success, failure, partial, blocked
- `BranchLifecycleStatus` — open, archived

### 4.4 Validation Rules
- `@dataclass(frozen=True)` — immutable after creation
- `schema_version` required, unknown version fails closed
- Empty strings rejected
- ID pattern: `^[A-Za-z0-9_-]+$`
- Hash pattern: `^[0-9a-f]{64}$` (SHA-256)
- Timezone-naive datetime rejected
- `type(value) is int` — bool rejected
- Dict → immutable tuple conversion
- List → tuple conversion

---

## 5. Immutable Transition Journal Design

### 5.1 Pattern
```
immutable entity records + append-only lifecycle transition journal + derived current state
```

### 5.2 NarrativeTurnTransition
```python
@dataclass(frozen=True)
class NarrativeTurnTransition:
    schema_version: str
    transition_id: str
    turn_id: str
    scope: NarrativeScope
    from_state: TurnState
    to_state: TurnState
    reason_code: str
    operation_id: str | None
    occurred_at: str
    record_fingerprint: str
```

### 5.3 Legal Transitions
- `planned` → `awaiting_action` / `superseded`
- `awaiting_action` → `validating`
- `validating` → `validated` / `blocked` / `requires_clarification`
- `requires_clarification` → `awaiting_action`
- `validated` → `previewed`
- `previewed` → `confirmed`
- `confirmed` → `applied_to_branch`
- `applied_to_branch` → `included_in_chapter`
- `included_in_chapter` → `committed`

### 5.4 Terminal States
- `blocked`
- `committed`
- `superseded`

### 5.5 Illegal Transitions (rejected)
- `confirmed` → `planned`
- `committed` → any
- `blocked` → `validated`
- `planned` → `confirmed`
- `previewed` → `committed`
- Cross-scope transitions
- Transition replay with different content

---

## 6. Store Path & Atomic Semantics

### 6.1 NarrativeTurnStore Path Structure
```
data/narrative_turns/{timeline_id}/{branch_id}/
  plans/{turn_id}.json
  validations/{validation_id}.json
  results/{turn_id}.json
  transitions/{turn_id}/{transition_id}.json
  operations/{operation_id}.json
```

### 6.2 NarrativeBranchStore Path Structure
```
data/branches/{timeline_id}/
  branches/{branch_id}.json
  registry.json
  registry_events/{event_id}.json
```

### 6.3 Path Security
- ID pattern validation: `^[A-Za-z0-9_-]+$`
- Reject: `..`, `/`, `\`, NUL, drive letters, UNC paths
- Resolved parent containment check
- Root symlink/reparse fail-closed

### 6.4 Atomic Write
- `tempfile.mkstemp` + `os.replace`
- `fsync` before replace
- Temp file cleanup on failure
- No overwrite of existing immutable records

### 6.5 Idempotency
- `operation_id` collision detection
- Identical transition replay returns same result
- Different payload with same operation_id → `TRANSITION_COLLISION`

---

## 7. Branch Registry Semantics

### 7.1 Branch Entity
- Immutable `NarrativeBranch` record
- `lifecycle_status`: "open" or "archived"
- Root branch has `parent_branch_id: None`
- Non-root branches must have valid `parent_branch_id`
- `archived_at` must be set when archived

### 7.2 Registry
- `active_branch_id` points to one open branch per timeline
- Revision-based updates with backup/recovery
- Concurrent updates: first-wins

### 7.3 Operations
| Operation | Rules |
| --- | --- |
| Create | Root or child branch; cycle prevention |
| Select | Only open branches allowed |
| Archive inactive | Sets `lifecycle_status="archived"` |
| Archive active | Must specify replacement branch |
| Restore | Sets `lifecycle_status="open"` |

### 7.4 Cycle Prevention
- Parent cannot equal self
- `check_for_cycle()` traverses parent chain

---

## 8. Root Cause / Implementation Matrix

| Requirement | Implementation | Test Coverage |
| --- | --- | --- |
| Immutable contracts | `@dataclass(frozen=True)` + validation | `test_frozen_immutable` |
| Exactly 3 actions | `len(actions) == 3` check | `test_exactly_three_actions` |
| Action order 1,2,3 | `orders == {1, 2, 3}` | `test_action_order_must_be_123` |
| Duplicate action ID | Set-based uniqueness check | `test_duplicate_action_id_rejected` |
| Duplicate intent | Set-based uniqueness check | `test_duplicate_intent_rejected` |
| Validation XOR | `selected_action_id` vs `custom_action_text_hash` | `test_validation_recommended_xor_custom` |
| Branch lifecycle consistency | `archived_at` tied to `lifecycle_status` | `test_branch_lifecycle_consistency` |
| Scope binding | `scope.assert_matches()` | `test_scope_assert_matches` |
| Path containment | Resolved path check | `test_path_traversal_rejected` |
| Atomic write | `tempfile.mkstemp` + `os.replace` | `test_append_plan` |
| Transition idempotency | Fingerprint comparison | `test_transition_idempotency` |
| Terminal state | Enum-based check | `test_terminal_state_transition` |

---

## 9. File Changes

### 9.1 New Files
| File | Purpose |
| --- | --- |
| `story-os-demo/core/contracts/narrative_turn.py` | Immutable contracts |
| `story-os-demo/system/narrative_turn_store.py` | Append-only Turn store |
| `story-os-demo/system/narrative_branch_store.py` | Branch registry store |
| `story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py` | Focused tests |
| `docs/planning/PHASE_0D4_A.md` | Phase documentation |

### 9.2 Updated Files
| File | Changes |
| --- | --- |
| `docs/design/simulator_narrative_turn_contract_map.md` | Update to implementation artifact |
| `docs/design/simulator_narrative_turn_state_machine.md` | Update transition rules and persistence |
| `docs/design/simulator_branch_isolation_map.md` | Update branch registry schema |
| `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md` | Mark 0D4-A as PASSED |

---

## 10. Focused & Regression Commands

### 10.1 Focused Tests
```
cd d:\novel\StoryOS\story-os-demo
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py -v
```
**Result:** 46 passed in 3.17s

### 10.2 Compile Check
```
cd d:\novel\StoryOS\story-os-demo
python -m compileall .
```
**Result:** Clean (exit code 0)

### 10.3 Git Status
```
cd d:\novel\StoryOS
git status
```
**Result:** No staged changes; existing modifications unrelated to 0D4-A

---

## 11. Git Status

- **Branch:** `agent/phase-13-2-memory-repair`
- **Ahead:** 2 commits
- **Untracked:** New 0D4-A files (contracts, stores, tests, docs)
- **Modified:** Existing files (unrelated to 0D4-A)
- **No git add/commit/push performed**

---

## 12. Provider/Network/Token/Cost

- **Provider calls:** 0
- **Network calls:** 0
- **Tokens consumed:** 0
- **Cost:** 0

---

## 13. Canon/Chroma/Real Project Writes

- **Canon writes:** 0
- **Chroma writes:** 0
- **Real project writes:** 0 (tests use temporary projects only)

---

## 14. Known Limitations

1. **No API endpoints** — reserved for 0D4-E
2. **No Planner** — reserved for 0D4-B
3. **No Feasibility engine** — reserved for 0D4-B
4. **No UI** — reserved for 0D4-C
5. **No Chapter compilation** — reserved for 0D4-F
6. **No real branch migration** — reserved for 0D4-E

---

## 15. 0D4-B Entry Criteria

**Prerequisites for entering 0D4-B:**

| Criteria | Status |
| --- | --- |
| 0D4-A contracts implemented | ✅ |
| 0D4-A stores implemented | ✅ |
| 0D4-A tests pass | ✅ |
| 0D4-A documented | ✅ |
| OWNER authorization for 0D4-B | ⏳ |

**Phase 0D4-A: PASSED**
**Phase 0D4-B: NOT AUTHORIZED**