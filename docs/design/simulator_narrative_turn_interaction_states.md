# Simulator Narrative Turn — Interaction State Matrix

> Phase 0D4-C-P preflight artifact.  **No production UI code is changed
> by this document.**
>
> Authority: this matrix binds the 0D4-A/B backend states
> (context/feasibility/preview) and the 0D4-A Turn lifecycle state
> machine to the Narrative Turn workspace UI.  It is the single source
> of truth for "what does the UI render in state X".

## 1. State region map

| Region | State owner | Backend authority |
| --- | --- | --- |
| Situation Header | ContextWireDTO + branch registry (3 dimensions: Lifecycle / Activity / Narrative State Data) | `context.branch.lifecycle` (from `NarrativeBranch.lifecycle_status` / `snapshot.branch_open`); `context.branch.activity` (from `snapshot.branch_is_active`); `context.branch.narrative_state_data` (from `branch_state_revision` + `BRANCH_STATE_*` limitations); `context.limitations` |
| Narrative Situation | ContextWireDTO advisory data | `context.situation` fields (chapter_goal, active_conflicts, characters, locations, resources, world_rules, open_threads, time_window, dependencies); `context.evidence_codes`; `context.limitations` (server-side source: `NarrativeTurnContextSnapshot` accessors — not browser API) |
| Recommended Action Group | PlanWireDTO | `recommended_actions` (exactly 3) |
| Custom Action Composer | Local input + ValidationWireDTO | `custom_action_policy.max_length` (=200); feasibility pipeline |
| Feasibility Panel | ValidationWireDTO | `status` (4 values); `blocking_reasons`; `cost_explanation`; `risk_explanation` |
| Consequence Preview | PreviewWireDTO | `preview_fingerprint`; hedged content |
| Turn Primary Action | Composite (selected action + validation + preview + context) | 0D4-C: always disabled; 0D4-D: see §7 |
| Turn Status Notice | Live region only | — |

## 2. Context states (Situation Header)

| State | Trigger | Header chip | Status Notice | Primary Action | Plan/Feasibility/Preview |
| --- | --- | --- | --- | --- | --- |
| `initial` | workspace mounted, no context yet | none | `读取上下文中…` | disabled | empty |
| `loading` | context bind request in flight | `读取中` | `读取上下文中…` | disabled | previous retained (if any) |
| `ready` | context fingerprint computed; no limitations | gold `◆ DETERMINISTIC` | `上下文已就绪` | per selection | render |
| `incomplete` | context bound with advisory limitations (`*_SPARSE`, `BRANCH_STATE_UNAVAILABLE`) | muted `数据稀疏` per source | `部分数据不可用` | per selection (advisory) | render with limitation notes |
| `stale` | context fingerprint mismatch on re-bind | amber `上下文已过期` | `上下文已过期；请重新规划` | disabled | previous retained with stale veil |
| `branch_state_unavailable` | `BRANCH_STATE_UNAVAILABLE` limitation (Narrative State Data dimension) | muted `branch_state_unavailable` | `分支状态数据不可用` | per selection (advisory; branch still open+active) | render; rail notes unavailable state data |
| `branch_state_scope_mismatch` | `BRANCH_STATE_PROJECT_MISMATCH` / `TIMELINE_MISMATCH` / `BRANCH_MISMATCH` | amber `branch_state_scope_mismatch` | `分支状态数据作用域不匹配` | disabled | render with limitation note |
| `source_missing` | source version not found | amber `来源缺失` | `来源版本不可用` | disabled | plan cannot bind; show empty |
| `canon_changed` | active canon revision != plan's `canon_revision` | amber `Canon 已变更` | `Canon 已变更；请重新规划` | disabled | previous retained with stale veil |
| `error` | context bind raised `NarrativeTurnError` | red-amber `上下文错误` | `发生错误：{safe message}` (role=alert) | disabled | empty |
| `explicit_404` | URL points to non-existent project/timeline/branch/chapter | red-amber `未找到` | `请求的上下文不存在` (role=alert) | disabled | empty; **no fallback to default project** |

### 2.1 Branch dimension overlays (3 independent dimensions)

The header tracks **three independent** branch dimensions.  They are
NOT collapsed into a single "Branch State" chip.

#### 2.1.1 Lifecycle dimension (blocking when archived)

| Lifecycle status | Header chip | Status Notice | Primary Action | Plan render |
| --- | --- | --- | --- | --- |
| `open` (`snapshot.branch_open == true`) | (no extra chip) | n/a | per selection | render |
| `archived` (`snapshot.branch_open == false`) | red-amber `branch_archived` | `分支已归档` | disabled | render (read-only) |

#### 2.1.2 Activity dimension (blocking when inactive)

| Activity | Header chip | Status Notice | Primary Action | Plan render |
| --- | --- | --- | --- | --- |
| `active` (`snapshot.branch_is_active == true`) | green-amber `active` | n/a | per selection | render |
| `inactive` (`snapshot.branch_is_active == false`) | amber `branch_inactive` | `分支未激活` | disabled | render (read-only) |

#### 2.1.3 Narrative State Data dimension (advisory, never blocks plan render)

| State data | Header chip | Status Notice | Primary Action | Plan render |
| --- | --- | --- | --- | --- |
| `available` (`branch_state_revision` present, no `BRANCH_STATE_*` limitation) | (no extra chip) | n/a | per selection | render |
| `unavailable` (`BRANCH_STATE_UNAVAILABLE`) | muted `branch_state_unavailable` | `分支状态数据不可用` | per selection (advisory) | render with limitation note |
| `scope_mismatch` (`BRANCH_STATE_PROJECT_MISMATCH` / `TIMELINE_MISMATCH` / `BRANCH_MISMATCH`) | amber `branch_state_scope_mismatch` | `分支状态数据作用域不匹配` | disabled | render with limitation note |
| `invalid` (malformed branch-state file) | amber `branch_state_invalid` | `分支状态数据无效` | disabled | render with limitation note |

**Critical:** `branch_archived` (Lifecycle, blocking) is **not** the
same as `branch_state_unavailable` (Narrative State Data, advisory).
A URL pointing to an archived branch must surface the
`branch_archived` overlay, never `branch_unavailable`.

### 2.2 Forbidden transitions

| Attempt | Result |
| --- | --- |
| Render plan/feasibility while `loading` | forbidden; show skeleton |
| Render plan while `error` | forbidden; show error boundary |
| Auto-correct URL on `explicit_404` | forbidden; retain URL |
| Show fabricated evidence on `incomplete` | forbidden; show `未提供` for missing fields |

## 3. Recommended Action Group states

| State | Trigger | Visual | Selection allowed | Primary Action impact |
| --- | --- | --- | --- | --- |
| `loading` | plan request in flight | 3 skeleton rows (hairline pulse) | no | disabled |
| `ready` | plan received; exactly 3 actions | 3 rows rendered | yes | per selected row's feasibility |
| `selected` | user clicks/keys a row | gold left rule on selected row | yes (switch) | triggers feasibility request for this action |
| `unavailable` | row has non-empty `unavailable_reasons` | row rendered; status chip `不可用` + reason text | yes (for inspection) | does NOT enable primary action |
| `stale` | parent context changed after plan was received | rows rendered with stale veil (muted, amber rule) | no | disabled; `重新规划` secondary |
| `empty_fallback` | plan returned 0 actions (should never happen — contract guarantees 3) | single row `规划器未返回行动` | no | disabled; error notice |
| `error` | plan request failed | single row `规划失败：{safe message}` | no | disabled; announcement via TurnStatusNotice |

### 3.1 Per-row status derivation

A row's status chip is derived from:
1. If `unavailable_reasons` is non-empty → `不可用` + reasons
2. Else if feasibility has been requested for this action:
   - `allowed` → `可用`
   - `allowed_with_cost` → `带代价`
   - `requires_clarification` → `需补充`
   - `blocked` → `不可用` (with blocking reasons)
3. Else (no feasibility yet) → `待分析` (muted)

### 3.2 Forbidden treatments

| Treatment | Why forbidden |
| --- | --- |
| Hide `unavailable` rows | violates "不隐藏 unavailable 选项" |
| Compute status in UI | violates "UI never computes a status" |
| Color-only status | violates accessibility |
| Auto-select first row | violates explicit-selection principle |
| Reorder rows | violates `deterministic_order` |

## 4. Custom Action Composer states

| State | Trigger | Input state | Counter | Submit button | Feasibility Panel |
| --- | --- | --- | --- | --- | --- |
| `idle` | no input; no focus | empty | `0/200` | disabled | previous (if any) |
| `editing` | focus or input | visible text | live count | disabled (until normalized) | previous (superseded if recommended selected) |
| `validating` | input passes NFKC + control-char check | normalized text | normalized count | enabled | previous |
| `too_long` | `len(normalized) > 200` | text retained | count (red) | disabled | previous |
| `control_char_rejected` | NUL/control char detected | text retained | count | disabled | previous |
| `unparseable` | feasibility returns `ACTION_UNPARSEABLE` | text retained | count | enabled (retry) | `需补充` + `行动结构无法识别` |
| `ambiguous_target` | feasibility returns `ACTION_TARGET_AMBIGUOUS` | text retained | count | enabled (retry) | `需补充` + `行动目标不明确` |
| `ambiguous_object` | feasibility returns `ACTION_OBJECT_AMBIGUOUS` | text retained | count | enabled (retry) | `需补充` + `行动对象不明确` |
| `allowed` | feasibility returns `allowed` | text retained | count | enabled (resubmit) | `可用` |
| `allowed_with_cost` | feasibility returns `allowed_with_cost` | text retained | count | enabled (resubmit) | `带代价` |
| `requires_clarification` | feasibility returns `requires_clarification` | text retained | count | enabled (retry) | `需补充` |
| `blocked` | feasibility returns `blocked` | text retained | count | enabled (retry) | `不可用` |
| `checking` | feasibility request in flight | text retained | count | disabled | `分析中…` skeleton |
| `superseded_by_recommended` | user selected a recommended row after entering custom text | text retained (NOT cleared) | count | enabled (resubmit reactivates custom) | previous custom result retained with stale veil; recommended feasibility renders |
| `stale_response` | generation mismatch on response | text retained | count | enabled | previous retained; no announcement |

### 4.1 Counter semantics

- Counter shows `len(normalized_text)` / 200, NOT `len(raw_text)` / 200.
- Normalization: NFKC + strip + collapse internal whitespace (matches
  backend `normalize_custom_action`).
- Counter updates on every `input` event.
- The counter element has **no** `aria-live`.  It is plain text
  associated with the textarea via `aria-describedby` so screen readers
  can read it on focus, but it does not announce every keystroke.
- Threshold crossings (`150/200`, `190/200`, `200/200`, `201/200`) are
  announced **once** through the single Turn Status Notice live region
  (§10), never through the counter element.  Stale responses remain
  silent.  The counter and Turn Status Notice must never announce the
  same change simultaneously.

### 4.2 Boundary behaviors

| Input length | State | Submit |
| --- | --- | --- |
| 0 | `idle` | disabled |
| 1–200 (normalized) | `validating` → `allowed*` / `blocked` / `requires_clarification` | enabled |
| 200 (exactly limit) | `validating` | enabled (accepted) |
| 201+ (normalized) | `too_long` | disabled |
| 200 raw → 195 normalized (whitespace collapse) | `validating` (195/200) | enabled |

### 4.3 Forbidden treatments

| Treatment | Why forbidden |
| --- | --- |
| Clear text on recommended selection | violates "user may switch back" |
| Persist raw text to URL/localStorage | violates §16.2 of UI spec |
| Autocomplete suggestions | implies LLM assist (default: no) |
| Counter on raw length | violates normalization boundary |
| Submit on `Enter` without explicit button | violates "explicit submit" principle |

## 5. Feasibility Panel states

| State | Trigger | Status chip | Reason block | Costs block | Risks block | Primary Action |
| --- | --- | --- | --- | --- | --- | --- |
| `absent` | no action selected | none | none | none | none | disabled |
| `loading` | feasibility request in flight | `分析中…` (info) | skeleton | skeleton | skeleton | disabled |
| `allowed` | `status=allowed` | `可用` (green-amber, `◆`) | none (or advisory) | none | none | enabled (0D4-D) |
| `allowed_with_cost` | `status=allowed_with_cost` | `带代价` (amber, `◇`) | none | enumerate costs | enumerate risks | enabled (0D4-D) |
| `requires_clarification` | `status=requires_clarification` | `需补充` (violet, `◈`) | state missing dimension | none | none | disabled |
| `blocked` | `status=blocked` | `不可用` (red-amber, `×`) | enumerate blocking reasons | none | none | disabled |
| `stale` | parent context changed after feasibility | chip with stale veil | retained | retained | retained | disabled; `重新规划` secondary |
| `error` | feasibility request failed | `分析失败` (red-amber) | `发生错误：{safe message}` | none | none | disabled; announcement via TurnStatusNotice |

### 5.1 Status priority enforcement (backend authority)

The UI **never** computes the highest-priority status.  The backend
returns a single `status` field already resolved by priority
(`blocked > requires_clarification > allowed_with_cost > allowed`).
The UI renders only that status.

### 5.2 Reason code disclosure

| State | Disclosure default | Disclosure expanded |
| --- | --- | --- |
| `allowed` | hidden | n/a |
| `allowed_with_cost` | user-text costs/risks | mono `RESOURCE_COST_HIGH`, etc. |
| `requires_clarification` | user-text "缺少 {dimension}" | mono `ACTION_TARGET_AMBIGUOUS`, etc. |
| `blocked` | user-text reasons | mono `WORLD_RULE_CONFLICT`, `CAPABILITY_MISSING`, etc. |

### 5.3 Forbidden treatments

| Treatment | Why forbidden |
| --- | --- |
| Fuzzy labels (`也许可以`) | violates 4-status discipline |
| `blocked` with "继续确认" button | violates "blocked is terminal for this action" |
| `requires_clarification` without missing dimension | violates "must state which dimension is missing" |
| `allowed_with_cost` without cost enumeration | violates "must enumerate costs explicitly" |
| Computing priority in UI | violates backend authority |

## 6. Consequence Preview states

| State | Trigger | Visual | Primary Action |
| --- | --- | --- | --- |
| `absent` | no feasibility ready | none | per feasibility |
| `loading` | preview request in flight | skeleton with `生成预览中…` | disabled |
| `ready` | preview received; context matches | hedged content; `预计后果（定性）` heading | per feasibility (0D4-D: enabled if allowed*) |
| `stale` | parent context changed after preview | hedged content with stale veil (muted, amber rule); `上下文已变更` chip | disabled |
| `blocked` | preview request returned error or action is `blocked` | `无法生成预览：{reason}` | disabled |
| `error` | preview request failed (transport) | `预览生成失败：{safe message}` | disabled; announcement via TurnStatusNotice |

### 6.1 Hedging enforcement

Every preview block (`likely consequences`, `expected costs`, `expected
risks`) must be prefixed with a hedging cue from the allowed-verbs
list.  The UI does not synthesize these verbs from backend content —
the backend already provides hedged copy.  The UI's role is to render
the copy under a `预计后果（定性）` heading and reject any preview
payload containing forbidden verbs (defensive check on render; if
violated, show `预览内容异常` and refuse to render the offending
block).

### 6.2 Context match indicator

| Indicator | Source | Visual |
| --- | --- | --- |
| `上下文匹配` | `preview_fingerprint` matches re-bound context | green-amber chip |
| `上下文已变更` | mismatch | amber chip; stale veil; primary disabled |

## 7. Confirmation states (Turn Primary Action)

### 7.1 0D4-C (current phase)

Single state: `unavailable_in_current_phase`.

| Field | Value |
| --- | --- |
| Label | `确认服务尚未接入` |
| Disabled | yes (`disabled` + `aria-disabled="true"`) |
| Disabled reason | `aria-describedby="nt-primary-disabled-reason"` referencing always-visible `<p id="nt-primary-disabled-reason">行动确认将在 Phase 0D4-D 接入；当前仅支持规划、分析与预览。</p>` (not `title`-only; no hover required) |
| Visual | muted; no spinner; no success flash |

### 7.2 0D4-D future states (spec only, not implemented in 0D4-C)

| State | Trigger | Label | Visual | Disabled |
| --- | --- | --- | --- | --- |
| `disabled` | any enable condition in UI spec §10.3 unmet | `确认这一行动` | muted; `title` carries reason | yes |
| `enabled` | all 7 conditions met | `确认这一行动` | gold accent | no |
| `submitting` | confirm POST in flight | `确认中…` | spinner | yes |
| `success` | confirm POST returned 200 | `已确认` (1.5s) → `确认下一回合` | green-amber flash | yes (transient) |
| `collision` | `OPERATION_COLLISION` returned | `操作冲突` | amber; notice shows `operation_id` | yes; `重试` secondary |
| `stale_context` | `TURN_SOURCE_CHANGED` / `TURN_CANON_REVISION_CHANGED` returned | `上下文已变更` | amber; primary disabled | yes; `重新规划` secondary |
| `recovery_required` | partial write detected on retry | `需恢复` | amber; `重试相同 operation_id` secondary | yes |

### 7.3 Enable condition matrix (0D4-D spec)

| Selected action | Feasibility status | Preview | Context | Branch | Source | Pending request | Primary Action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | n/a | n/a | n/a | n/a | n/a | n/a | disabled |
| recommended | `allowed` | ready | fresh | open+active | unchanged | none | **enabled** |
| recommended | `allowed_with_cost` | ready | fresh | open+active | unchanged | none | **enabled** |
| recommended | `requires_clarification` | any | any | any | any | any | disabled |
| recommended | `blocked` | any | any | any | any | any | disabled |
| recommended | any | stale | any | any | any | any | disabled |
| recommended | any | any | stale | any | any | any | disabled |
| recommended | any | any | any | archived | any | any | disabled |
| recommended | any | any | any | not active | any | any | disabled |
| recommended | any | any | any | any | changed | any | disabled |
| recommended | any | any | any | any | any | in-flight | disabled |
| custom | `allowed` | ready | fresh | open+active | unchanged | none | **enabled** |
| custom | `allowed_with_cost` | ready | fresh | open+active | unchanged | none | **enabled** |
| custom | `requires_clarification` | any | any | any | any | any | disabled |
| custom | `blocked` | any | any | any | any | any | disabled |

### 7.4 Forbidden confirm behaviors

| Behavior | Why forbidden |
| --- | --- |
| Fake success in 0D4-C | violates "不得伪造成功确认" |
| Enable on `blocked` | violates "blocked always disables" |
| Enable on `requires_clarification` | violates "requires_clarification always disables" |
| Enable on stale preview | violates "preview must be current" |
| Enable on stale context | violates "context must not be stale" |
| Multiple primary actions | violates single-primary-action rule |

## 8. Cross-region state transitions

### 8.1 Recommended action selection flow

```
[ready, no selection]
  → user clicks row 2
  → [ready, row 2 selected]
  → fire feasibility request (AbortController armed)
  → [ready, row 2 selected, feasibility loading]
  → response arrives (generation matches)
  → [ready, row 2 selected, feasibility allowed_with_cost]
  → fire preview request
  → [ready, row 2 selected, feasibility allowed_with_cost, preview ready]
  → primary action: enabled (0D4-D) / disabled (0D4-C)
```

### 8.2 Custom action submission flow

```
[ready, no selection]
  → user focuses composer, types text
  → [ready, custom editing, counter 42/200]
  → user clicks "分析可行性"
  → fire feasibility request (AbortController armed)
  → [ready, custom checking]
  → response arrives (generation matches)
  → [ready, custom allowed_with_cost, feasibility allowed_with_cost]
  → fire preview request
  → [ready, custom allowed_with_cost, preview ready]
```

### 8.3 Mutual exclusion flow

```
[ready, row 2 selected, feasibility allowed_with_cost]
  → user focuses composer, types text, submits
  → row 2 selection cleared (visually; gold rule removed)
  → row 2 feasibility retained with stale veil (superseded)
  → custom feasibility request fires
  → [ready, custom checking, row 2 superseded]
```

```
[ready, custom allowed_with_cost]
  → user clicks row 1
  → custom "active" selection cleared (text retained; feasibility retained with stale veil)
  → row 1 feasibility request fires
  → [ready, row 1 selected, custom superseded]
```

### 8.4 Parent context change flow

```
[ready, row 2 selected, feasibility allowed_with_cost, preview ready]
  → user changes chapter in Context Navigator
  → AbortController.abort() on all in-flight requests
  → storyosRequestGeneration += 1
  → [loading, no selection]
  → context re-bind
  → [ready (new context)] or [error] or [explicit_404]
  → if ready: plan re-fetch
  → [ready (new), plan loading]
  → [ready (new), plan ready, no selection]
  → focus → workspace h1
  → aria-live: "上下文已就绪"
```

### 8.5 Stale response flow

```
[ready, row 2 selected, feasibility loading (gen=5)]
  → user clicks row 3 (gen=6)
  → AbortController.abort() on row 2's request
  → row 3 feasibility request fires (gen=6)
  → row 2's response arrives late (gen=5 ≠ 6)
  → silently discard row 2's response
  → do not announce
  → do not render
  → row 3's response arrives (gen=6)
  → render row 3's feasibility
```

## 9. State → DOM mapping (contractual)

| State | DOM attribute | Value |
| --- | --- | --- |
| Context `loading` | `#narrative-turn-workspace[data-context-state]` | `loading` |
| Context `ready` | same | `ready` |
| Context `stale` | same | `stale` |
| Context `error` | same | `error` |
| Row `selected` | `row[data-selected]` | `true` |
| Row `unavailable` | `row[data-unavailable]` | `true` |
| Composer `too_long` | `composer[data-state]` | `too_long` |
| Feasibility `blocked` | `feasibility-panel[data-status]` | `blocked` |
| Preview `stale` | `preview[data-stale]` | `true` |
| Primary `disabled` | `button[disabled]` + `button[aria-disabled]` | `true`/`true` |

These `data-*` attributes are the **only** DOM contract that
production 0D4-C tests may assert against.  CSS selectors in
`simulator-narrative-turn.css` must use these attributes, not
ad-hoc classes.

## 10. Live region announcement matrix

| Trigger | Region | `aria-live` | Text |
| --- | --- | --- | --- |
| Context loaded | Turn Status Notice | polite | `上下文已就绪` |
| Context load failed | Turn Status Notice | assertive (role=alert) | `发生错误：{safe message}` |
| Plan loaded | Turn Status Notice | polite | `已生成 3 个推荐行动` |
| Action selected | Turn Status Notice | polite | `已选择行动 {order}：{intent}` |
| Feasibility ready | Turn Status Notice | polite | `可行性分析完成：{status label}` |
| Feasibility error | Turn Status Notice | assertive (role=alert) | `可行性分析失败：{safe message}` |
| Preview ready | Turn Status Notice | polite | `预览已生成（定性）` |
| Preview error | Turn Status Notice | assertive (role=alert) | `预览生成失败：{safe message}` |
| Stale response ignored | (none) | — | silent |
| Counter threshold crossed (`150/200`, `190/200`, `200/200`, `201/200`) | Turn Status Notice | polite | one-time `{count}/200` announcement; counter element itself has **no** `aria-live` |
| Counter update (non-threshold) | (none) | — | silent (counter is plain text via `aria-describedby`) |
| Primary action enabled | (none) | — | silent (visual only) |
| Primary action disabled | (none) | — | silent (visual only) |

**Single live region rule:** Turn Status Notice is the **only**
business live region.  The counter element must not carry
`aria-live`.  Threshold crossings are announced **once** via Turn
Status Notice; non-threshold counter updates are silent.  The counter
and Turn Status Notice must never announce the same change
simultaneously.

## 11. State recovery rules

| Scenario | Recovery |
| --- | --- |
| Page reload mid-flow | re-bind from URL; render `loading` → `ready` |
| Back/Forward | `popstate` re-binds; AbortController aborts in-flight |
| Network drop during feasibility | `error` state; `重试` secondary; previous plan retained |
| Network drop during preview | `error` state; `重试` secondary; previous feasibility retained |
| URL points to archived branch | `branch_archived` (Lifecycle) blocking state; primary disabled; no auto-redirect. **Not** `branch_state_unavailable` (which is advisory). |
| URL points to non-existent chapter | `explicit_404` for chapter; no fallback to chapter 1 |
| Context stale on confirm attempt (0D4-D) | `stale_context` state; `重新规划` secondary |

## 12. State matrix completeness checklist

| Region | States defined | Transitions defined | DOM contract defined |
| --- | --- | --- | --- |
| Context | 10 (§2) + 3 branch dimension overlays (§2.1.1–2.1.3) | §8.4, §8.5 | `data-context-state` (§9) |
| Recommended Action Group | 7 (§3) + 3 per-row (§3.1) | §8.1, §8.3 | `data-selected`, `data-unavailable` (§9) |
| Custom Action Composer | **15** (§4: idle/editing/validating/too_long/control_char_rejected/unparseable/ambiguous_target/ambiguous_object/allowed/allowed_with_cost/requires_clarification/blocked/checking/superseded_by_recommended/stale_response) | §8.2, §8.3 | `data-state` (§9) |
| Feasibility Panel | 8 (§5) | §8.1, §8.2 | `data-status` (§9) |
| Consequence Preview | 6 (§6) | §8.1, §8.2 | `data-stale` (§9) |
| Confirmation (0D4-C) | 1 (§7.1) | n/a | `disabled`, `aria-disabled`, `aria-describedby` (§9) |
| Confirmation (0D4-D spec) | 7 (§7.2) + matrix (§7.3) | n/a (spec only) | spec only |
| Turn Status Notice | 12 announcements (§10) — only business live region; counter has no `aria-live` | §8 | `aria-live` (§10) |

## 13. HTTP Wire DTO and data flow

### 13.1 HTTP methods

| Endpoint | Method | Body | Response |
| --- | --- | --- | --- |
| `/api/narrative-turn/context` | `GET` | none (query params) | ContextWireDTO |
| `/api/narrative-turn/plan` | `GET` | none (query params) | PlanWireDTO |
| `/api/narrative-turn/feasibility` | `POST` | JSON body (scope + action selection) | ValidationWireDTO |
| `/api/narrative-turn/preview` | `POST` | JSON body (scope + action selection) | PreviewWireDTO |

All endpoints return `Cache-Control: no-store`.

### 13.2 Data layer separation

```
Python Domain Contract (server-side only)
  → server-side DTO adapter
  → JSON Wire DTO (HTTP response)
  → JavaScript view model (client-side)
  → DOM renderer
```

Python accessors (`planning_data_dict()`, `chapter_plan_dict()`, etc.)
are server-side only.  They are **not** browser API methods.

### 13.3 Custom action text security

- Raw text exists only in the current request body (POST JSON)
- Never enters URL, localStorage, file system, or access logs
- Never echoed in response
- Backend returns only SHA-256 hash
- Frontend retains text only in textarea memory state

### 13.4 Error envelope

```json
{
  "error": {
    "code": "CONTEXT_STALE",
    "message": "上下文已过期，请重新规划。",
    "request_id": null
  }
}
```

Status codes: `400` malformed, `404` not found, `409` stale, `422` rejected, `500` safe internal error.

`allowed` / `allowed_with_cost` / `requires_clarification` / `blocked`
are **successful** feasibility responses, NOT HTTP transport errors.

### 13.5 Unavailable radio semantics

```
unavailable action:
- remains natively selectable for inspection
- row has data-unavailable="true"
- radio has aria-describedby referencing visible reason
- radio does NOT have aria-disabled
- radio is NOT natively disabled
- backend feasibility remains authority
- primary confirmation never becomes enabled
```

Stale action group uses native `disabled` on all radios.

### 13.6 Single live region

TurnStatusNotice (`#nt-status-notice`) is the **only** business live region.
It toggles between:
- Normal: `role="status"` + `aria-live="polite"`
- Error: `role="alert"` + `aria-live="assertive"`

FeasibilityPanel, ConsequencePreview, RecommendedActionGroup,
CustomAction counter, and workspace error content have **no**
`aria-live` and **no** `role="alert"`.  They display visible text;
announcements are routed through TurnStatusNotice.

### 13.7 Stale response handling

Stale responses (generation mismatch) are:
- silently discarded
- never rendered
- never announced
- previous valid result is retained
