# Simulator Narrative Turn Workspace — UI Specification

> Phase 0D4-C-P preflight artifact.  Produced with the `frontend-design`
> Skill.  **No production UI code is changed by this document.**
>
> Authority: this spec extends the locked 0D3A visual direction
> (Night editorial desk / evidence rail) and binds it to the 0D4-A/B
> data contracts.  It must be implemented verbatim by Phase 0D4-C.

## 1. Design read

| Input | Source | Locked fact |
| --- | --- | --- |
| Visual direction | [simulator_visual_direction.md](file:///d:/novel/StoryOS/docs/design/simulator_visual_direction.md) | Night editorial desk; gold `#bca374` authority; violet `#7c6cf2` supplement; hairline borders; editorial serif headings; mono ids |
| CSS token inventory | [simulator_css_token_inventory.md](file:///d:/novel/StoryOS/docs/design/simulator_css_token_inventory.md) | `--bg-base #080b10`, `--bg-workspace #0c1118`, `--bg-elevated #111721`, `--story-gold`, `--accent-primary`, `--status-*`, `--font-editorial/body/mono` |
| Shell architecture | [simulator_frontend_architecture_audit.md](file:///d:/novel/StoryOS/docs/design/simulator_frontend_architecture_audit.md) | Single-page `index.html`; mode switch `traditional`/`simulator`; vanilla JS modules; no build tool; `storyosApiGet/Post` with `AbortController` + `storyosRequestGeneration` |
| Existing workspace | [simulator_context_navigator.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator_context-navigator.js), [simulator_panel_review.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-panel-review.js) | `parseContext()` URL validation; `safeText()`/`node()` builders; `statusChip()`; `aria-live="polite"`; gold 2px `:focus-visible` |
| Data contracts | [simulator_narrative_turn_contract_map.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_contract_map.md) | `NarrativeTurnPlan` (exactly 3 `recommended_actions`), `NarrativeActionOption`, `NarrativeActionValidation` (4 statuses), `NarrativeCustomActionPolicy.max_length=200` |
| Feasibility engine | [simulator_action_feasibility.md](file:///d:/novel/StoryOS/docs/design/simulator_action_feasibility.md) | 14-step pipeline; `blocked > requires_clarification > allowed_with_cost > allowed`; reason codes from §5 |
| Planner | [simulator_narrative_turn_planner.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_planner.md) | `planner_revision = "narrative-turn-planner-v1"`; 8 candidate categories; exactly 3 actions; stable `action_id` |

**Design parameters:** `DESIGN_VARIANCE: 5–6`, `MOTION_INTENSITY: 2–3`,
`VISUAL_DENSITY: 7`.

**Skill directive applied:** the `frontend-design` skill pushes for bold
aesthetic differentiation, but the OWNER-locked 0D3A direction and the
"do not create another product" constraint (Phase 0D4-C-P §6) override
pure-aesthetic maximalism.  The aesthetic commitment here is **refined
editorial restraint**, executed with the precision the skill demands:
typographic hierarchy, hairline rhythm, gold authority marks, and a
single decisive motion vocabulary.  No new font, no new palette, no new
motion system.

## 2. Product goal

A desktop-first, restrained, narrative-priority workspace where the
author can:

```
understand the current situation
→ compare 3 recommended actions
→ or enter a custom action
→ read deterministic feasibility
→ read qualitative consequence preview
→ know exactly whether the next step can be confirmed
```

The workspace must **not** read as a data dashboard, a card game, a
chat window, a marketing page, a generic admin panel, or a neon sci-fi
interface.

## 3. Information architecture

Narrative Turn is a **workspace inside the existing Simulator Shell**,
not a new page.  It reuses the global sidebar, topbar, mode switch, and
Context Navigator.

```
Simulator Shell (existing)
├── Global Sidebar (existing, unchanged)
├── Topbar (existing, mode=simulator)
├── Context Navigator (existing, extends to branch_id)
└── Narrative Turn Workspace (new section, view=narrative-turn)
    ├── Situation Header
    ├── Narrative Situation (evidence summary)
    ├── Recommended Action Group (3 rows)
    ├── Custom Action Composer
    ├── Feasibility Panel
    ├── Consequence Preview
    ├── Turn Primary Action
    └── Turn Status Notice (live region)
```

### 3.1 Visibility rules

| Region | Always visible | On selection | Error state only |
| --- | --- | --- | --- |
| Situation Header | yes | — | — |
| Narrative Situation | yes (collapsed summary) | expanded on "查看依据" | — |
| Recommended Action Group | yes (3 rows) | highlighted row | — |
| Custom Action Composer | yes (collapsed prompt) | expanded on focus | — |
| Feasibility Panel | — | yes (after action selected/entered) | yes (blocked / error) |
| Consequence Preview | — | yes (after feasibility ready) | yes (preview error) |
| Turn Primary Action | yes (footer-pinned) | label/state changes | disabled with reason |
| Turn Status Notice | — | — | yes (live region) |

### 3.2 Layout — desktop (≥1280px)

```
┌──────┐┌────────────────────────────────────────────────┐┌────────────┐
│      ││ Topbar (existing)                              ││            │
│      │├────────────────────────────────────────────────┤│  Evidence  │
│      ││ Situation Header                               ││   Rail     │
│ Side │├────────────────────────────────────────────────┤│            │
│  bar ││ Narrative Situation                           ││ limitations│
│      │├────────────────────────────────────────────────┤│ costs      │
│      ││ Recommended Action Group (3 vertical rows)     ││ risks      │
│      │├────────────────────────────────────────────────┤│ reason code│
│      ││ Custom Action Composer                         ││ freshness  │
│      │├────────────────────────────────────────────────┤│            │
│      ││ Feasibility Panel                              ││            │
│      │├────────────────────────────────────────────────┤│            │
│      ││ Consequence Preview                            ││            │
│      │├────────────────────────────────────────────────┤│            │
│      ││ [Turn Primary Action — footer-pinned]          ││            │
└──────┘└────────────────────────────────────────────────┘└────────────┘
```

The Evidence Rail is the continuation of the 0D3A audit rail.  It is
**not** a new column system — it is the same right-hand ruled ledger,
now populated with Turn evidence, costs, risks, and reason codes.

### 3.3 Layout — narrow desktop / tablet (≤900px)

The Evidence Rail collapses into a vertical stack **below** the
Feasibility Panel.  The three recommended action rows remain stacked
and comparable.  No horizontal scroll.

### 3.4 Layout — mobile (≤760px)

Single-column priority order: Situation Header → Narrative Situation
(collapsed) → Recommended Action Group → Custom Action Composer →
Feasibility Panel → Consequence Preview → Turn Primary Action →
Evidence Rail (collapsed, "查看依据" disclosure).

## 4. Situation Header

### 4.1 Required fields

| Field | Source | Display |
| --- | --- | --- |
| Project | `scope.project_id` | name (escaped) |
| Timeline | `scope.timeline_id` | id (mono) |
| Branch | `scope.branch_id` | id (mono) + lifecycle badge |
| Chapter | `chapter_id` | `第 N 章` |
| Source Version | `source_version_id` | label or `当前源` |
| Canon Revision | `canon_revision` | short id (mono, first 8 chars) |
| Context Freshness | `context_fingerprint` mismatch | `新鲜` / `已过期` badge |
| Branch Lifecycle | `NarrativeBranch.lifecycle_status` / `snapshot.branch_open` | `open` / `archived` |
| Branch Activity | `snapshot.branch_is_active` / registry `active_branch_id` | `active` / `inactive` |
| Narrative State Data | `branch_state_revision` + `BRANCH_STATE_*` limitations | `available` / `unavailable` / `scope_mismatch` / `invalid` |
| Planner Revision | `planner_revision` | mono stamp `narrative-turn-planner-v1` |

**Never display the full `context_fingerprint`.**  Show only the first
8 hex chars as an audit mark, with `title` carrying the meaning
"上下文审计标记（非完整指纹）".

### 4.2 Header states

| State | Visual treatment | Blocking? |
| --- | --- | --- |
| Context ready | gold rule + `◆ DETERMINISTIC` stamp; no banner | no |
| Narrative state data unavailable | muted badge `branch_state_unavailable`; rail note | no (advisory) |
| Advisory data missing | muted `数据缺失` chip per missing source | no (advisory) |
| Source stale | amber chip `来源已变更` | yes (re-plan required) |
| Canon changed | amber chip `Canon 已变更` | yes (re-plan required) |
| Branch archived (lifecycle) | red-amber chip `branch_archived`; primary action disabled | yes |
| Branch inactive (activity) | red-amber chip `branch_inactive`; primary action disabled | yes |
| Planning missing | amber chip `PLANNING_DATA_MISSING` | yes (re-plan required) |
| Context invalid | red-amber chip `上下文无效`; full notice in Turn Status Notice | yes |

Blocking states do **not** use a large red banner.  They use a
hairline amber/red-amber chip in the header plus a single line in the
Turn Status Notice live region.  Color is never the only signal —
every chip carries a literal Chinese label.

## 5. Narrative Situation region

### 5.1 Hierarchy

| Tier | Evidence class | Source | Visual |
| --- | --- | --- | --- |
| 1 | Authority | chapter goal, active conflicts, world rules, character capabilities, resources, locations, planning dependencies | gold left rule; editorial serif heading |
| 2 | Advisory | reader persona projections, model supplement (future) | violet inset; muted |
| 3 | Unavailable | missing/invalid data with `*_MISSING`/`*_INVALID` limitation | hairline grey; `未提供` label; never fabricated |

### 5.2 Required content

- 当前章节目标 (chapter goal)
- 当前冲突 (active conflicts)
- 角色与位置 (characters + locations)
- 可用资源 (resources)
- 世界规则约束 (world rules / taboos)
- 未解决线索 (unresolved plot threads)
- 时间窗口 (time window)
- 已知限制 (limitations — from context snapshot)

### 5.3 "查看依据" disclosure

A low-weight text button (`按钮`-styled link, not a primary control)
toggles the evidence breakdown: source file, revision, fingerprint
prefix.  This is **collapsed by default** to keep the situation
readable.  Disclosure does not trigger any API call — it reveals
already-bound snapshot data.

The raw JSON of `story_planning.json` / `world_bible.json` /
`characters.json` is **never** dumped.  Only structured, labeled
fields are shown.

## 6. Recommended Action Group

### 6.1 Layout decision: vertical decision list

Three recommended actions are rendered as a **vertical list of
comparable rows**, not a three-column card grid.  This matches the
editorial-desk metaphor (a marked-up decision sheet, not a skill
palette) and keeps all three options readable on narrow screens.

Each row:

```
┌──────────────────────────────────────────────────────────────────┐
│ ①  advance · 推进主线目标                                        │
│    调查迷雾森林中失踪旅人的下落                                   │
│    costs: time·high, resource·medium    risks: safety·high       │
│    [status chip: 可用 / 带代价 / 需补充 / 不可用 + reason]        │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 Row anatomy

| Element | Source field | Treatment |
| --- | --- | --- |
| Order marker | `deterministic_order` | circled ①②③; gold for selected, hairline for others |
| Action type | `action_type` | mono kicker, lowercase |
| Intent | `intent` | editorial serif, one line |
| Display text | `display_text` | body sans, secondary color, wrapped |
| Costs | `expected_costs` | mono `key·level` pairs, muted |
| Risks | `expected_risks` | mono `key·level` pairs, muted |
| Status | derived from `unavailable_reasons` + feasibility | chip: `可用` / `带代价` / `需补充` / `不可用` |
| Unavailable reason | `unavailable_reasons` | inline text below status; never hidden |

### 6.3 Selection semantics

- Selection uses **native radio inputs** inside a `<fieldset>` with
  `<legend>`.  Each row is a `<label class="nt-action-row">` wrapping
  a native `<input type="radio" name="narrative-turn-action">`.
- The browser's native radio behavior provides arrow-key navigation
  (`↑`/`↓`/`←`/`→`), `Space` to select, and `Tab` to enter/exit the
  group.  No custom roving tabindex is required.
- Only one recommended action can be selected at a time (native radio
  mutual exclusion via shared `name` attribute).
- Selecting a recommended action **clears** any custom action selection
  (mutual exclusion — see §7.4).
- Selected row gets a gold left rule (2px).  The native `checked`
  attribute reflects selection; do not duplicate it with
  `aria-checked`.
- Selecting an `unavailable` row is **allowed** (so the user can read
  its reason and evidence), but it does **not** enable the primary
  action.  Unavailable rows use `data-unavailable="true"` on the row
  and `aria-describedby` on the radio pointing to visible reason text,
  not `aria-disabled` or native `disabled`.  Backend feasibility is the
  final authority — unavailable rows never enable confirmation.

### 6.4 Forbidden treatments

- No three-column "skill card" grid.
- No icons that imply game mechanics (swords, shields, mana).
- No hover-only revelation of costs/risks — they are always visible.
- No color-only status — every chip has a Chinese label.

## 7. Custom Action Composer

### 7.1 Layout

A single-line prompt that expands to a textarea on focus.  It is
visually distinct from the recommended rows: a hairline inset with a
violet accent (the `--accent-primary` supplement color), signaling
"this is your own input, not deterministic output".

### 7.2 Required affordances

| Affordance | Implementation |
| --- | --- |
| Max length notice | `最多 200 个规范化字符` (static text, mono) |
| Counter | `<current>/<max>` mono, plain text via `aria-describedby`; **no `aria-live` on counter itself** |
| Persistence notice | `文本仅用于当前可行性分析；仅保留 SHA-256` (static, muted) |
| Non-execution notice | `不会作为系统命令执行` (static, muted) |
| Submit | `分析可行性` button (secondary, not primary) |

The counter is plain text associated with the textarea via
`aria-describedby`.  It must **not** carry its own `aria-live`.
Threshold crossings (`150/200`, `190/200`, `200/200`, `201/200`) are
announced **once** through the single Turn Status Notice live region
(§11), never through the counter element itself.

### 7.3 Composer states

| State | Trigger | Visual |
| --- | --- | --- |
| empty | no input | placeholder `输入自定义行动…` |
| editing | focus or input | violet focus ring; counter active |
| normalized | input passes NFKC + control-char check | green-amber chip `已规范化` |
| too long | `len > 200` | amber chip `ACTION_TOO_LONG`; submit disabled |
| control character rejected | NUL/control char detected | amber chip `ACTION_UNPARSEABLE`; submit disabled |
| unparseable | feasibility returns `ACTION_UNPARSEABLE` | red-amber chip in Feasibility Panel |
| ambiguous target | `ACTION_TARGET_AMBIGUOUS` | amber chip in Feasibility Panel |
| ambiguous object | `ACTION_OBJECT_AMBIGUOUS` | amber chip in Feasibility Panel |
| recognized | feasibility returns `allowed*` | green-amber chip in Feasibility Panel |
| checking | request in flight | spinner + `分析中…`; stale-response guard active |
| stale response ignored | generation mismatch | silent; previous result kept |
| feasibility ready | response received | Feasibility Panel renders |

### 7.4 Mutual exclusion with recommended actions

- Selecting a recommended action clears the composer's "active"
  selection state (the composer remains editable, but its feasibility
  result is **superseded** — see interaction states doc).
- Submitting the composer (clicking `分析可行性`) clears any
  recommended action selection.
- The composer textarea content is **not** cleared by selecting a
  recommended action — the user may switch back.  But the feasibility
  result shown is always for the currently-selected action source.

### 7.5 Forbidden treatments

- No chat-window styling (no bubble, no avatar, no "send" arrow).
- No autocomplete/suggestion dropdown (would imply LLM assist, which
  is `default: no` per architecture map §7).
- No persistence of raw text to URL, localStorage, or any store.

## 8. Feasibility Panel

### 8.1 Four-status rendering

| Status | Label | Color | Icon | Primary action |
| --- | --- | --- | --- | --- |
| `allowed` | `可用` | green-amber | `◆` | enabled (0D4-D) |
| `allowed_with_cost` | `带代价` | amber | `◇` | enabled (0D4-D) |
| `requires_clarification` | `需补充` | violet | `◈` | disabled |
| `blocked` | `不可用` | red-amber | `×` | disabled |

Status priority is enforced by the backend (`blocked >
requires_clarification > allowed_with_cost > allowed`); the UI only
renders the received status.  The UI **never** computes a status.

### 8.2 Required content

- Status label (Chinese) + status code (mono, in `title`).
- User-facing reason text (mapped from `blocking_reasons` / reason
  codes — see §8.3).
- `cost_explanation` block (separate from risks).
- `risk_explanation` block (separate from costs).
- "查看原始 reason code" disclosure (collapsed; shows mono codes like
  `CAPABILITY_MISSING`, `RESOURCE_COST_HIGH`).
- Evidence section (linked to Evidence Rail).
- Limitations section (separate from evidence).

### 8.3 Reason-code → user-text mapping

| Code | User text |
| --- | --- |
| `ACTION_EMPTY` | 行动为空 |
| `ACTION_TOO_LONG` | 行动超过 200 字符上限 |
| `ACTION_UNPARSEABLE` | 行动结构无法识别 |
| `ACTION_TARGET_AMBIGUOUS` | 行动目标不明确 |
| `ACTION_OBJECT_AMBIGUOUS` | 行动对象不明确 |
| `CONTEXT_STALE` | 上下文已过期 |
| `SOURCE_STALE` | 来源版本已变更 |
| `CONTEXT_INSUFFICIENT` | 上下文证据不足 |
| `BRANCH_NOT_ACTIVE` | 分支未激活 |
| `BRANCH_ARCHIVED` | 分支已归档 |
| `WORLD_RULE_CONFLICT` | 与世界规则冲突 |
| `CANON_CONFLICT` | 与已确立 Canon 冲突 |
| `CAPABILITY_MISSING` | 角色能力不足 |
| `RESOURCE_MISSING` | 资源不存在 |
| `RESOURCE_COST_HIGH` | 资源代价较高 |
| `LOCATION_MISMATCH` | 位置不匹配 |
| `TIME_WINDOW_CLOSED` | 时间窗口已关闭 |
| `RELATIONSHIP_PERMISSION_MISSING` | 关系或权限不足 |
| `DEPENDENCY_BLOCKED` | 前置依赖未完成 |

### 8.4 Forbidden treatments

- No fuzzy labels like `也许可以` / `可能不行` / `待定`.
- `blocked` must visually read as terminal for this action — no
  "继续确认" affordance.
- `requires_clarification` must state which dimension is missing
  (target / object / capability / resource / location / time /
  relationship / dependency).
- `allowed_with_cost` must enumerate the costs explicitly; never just
  "有代价".

## 9. Consequence Preview

### 9.1 Hedging requirement

Preview copy **must** use hedged verbs.  The UI enforces this by
rendering the preview under a `预计后果（定性）` heading and
prefixing each block with a hedging cue.

| Allowed verbs | Forbidden verbs |
| --- | --- |
| 可能 / 预计 / 倾向于 / 可能导致 / 或将 | 已经发生 / 必然 / 将会 / 系统确认 / 注定 |

### 9.2 Required content

- `likely consequences` block (hedged)
- `expected costs` block (hedged)
- `expected risks` block (hedged)
- `evidence` block (read-only)
- `limitations` block (read-only)
- `preview freshness` indicator (timestamp + fingerprint prefix)
- `context match` indicator (`上下文匹配` / `上下文已变更`)

### 9.3 Forbidden treatments

- No prose styling that mimics novel body text (no drop cap, no
  justified paragraph, no chapter-style indent).
- No "确认该结果" button — preview is read-only.
- If `context match` is `已变更`, the preview is rendered with a
  stale veil (muted, amber left rule) and the primary action is
  disabled.

## 10. Turn Primary Action

### 10.1 Single-primary-action rule

The workspace has **exactly one** primary action, footer-pinned in the
main content column.  There are no competing primary buttons.  All
other affordances (custom action submit, "查看依据") are secondary or
tertiary.

### 10.2 0D4-C state (current phase)

```html
<button type="button" class="nt-primary-action" disabled
        aria-disabled="true"
        aria-describedby="nt-primary-disabled-reason">
  确认服务尚未接入
</button>
<p id="nt-primary-disabled-reason" class="nt-primary-disabled-reason">
  行动确认将在 Phase 0D4-D 接入；当前仅支持规划、分析与预览。
</p>
```

The button is always disabled in 0D4-C.  It never fakes a success
confirmation.  Its `aria-disabled="true"` and `disabled` attributes
are both set.  The disabled reason is **always visible** as plain text
and associated via `aria-describedby` so screen readers announce it
without requiring hover or focus.  The `title` attribute is **not**
the sole carrier of the disabled reason.

### 10.3 0D4-D enabled conditions (spec, not implemented)

The primary action `确认这一行动` is enabled only when **all** are
true:

| Condition | Source |
| --- | --- |
| selected action exists | recommended `selected_action_id` OR custom `custom_action_text_hash` |
| validation status is `allowed` or `allowed_with_cost` | `NarrativeActionValidation.status` |
| preview is current | `preview_fingerprint` matches current context |
| context not stale | `context_fingerprint` matches re-bound snapshot |
| branch active/open | branch lifecycle = `open` AND is active |
| source unchanged | `source_fingerprint` matches plan |
| no pending request | no in-flight confirm POST |

`blocked` and `requires_clarification` **always** disable the primary
action, regardless of other conditions.

### 10.4 Future confirm states (spec only, not implemented in 0D4-C)

| State | Label | Visual |
| --- | --- | --- |
| submitting | `确认中…` | spinner; button disabled |
| success | `已确认` (transient) | green-amber flash 1.5s; then `确认下一回合` |
| collision | `操作冲突` | amber; `operation_id` shown in notice |
| stale context | `上下文已变更` | amber; primary disabled; `重新规划` secondary |
| recovery required | `需恢复` | amber; `重试相同 operation_id` secondary |

## 11. Turn Status Notice (live region)

A single `aria-live="polite"` region below the Situation Header.  It
carries at most one line of status text.  It is the **only** region
that may announce state changes to screen readers.

| Trigger | Text |
| --- | --- |
| Context loaded | `上下文已就绪` |
| Branch-state unavailable | `分支状态不可用；使用 BRANCH_STATE_UNAVAILABLE` |
| Source stale | `来源已变更；请重新规划` |
| Action selected | `已选择行动 N：{intent}` |
| Feasibility ready | `可行性分析完成：{status label}` |
| Preview ready | `预览已生成（定性）` |
| Stale response ignored | (silent — do not announce) |
| Error | `发生错误：{safe message}` (role=alert) |

## 12. Visual system

### 12.1 Reused tokens (no new palette)

| Token | Use |
| --- | --- |
| `--bg-workspace #0c1118` | workspace background |
| `--bg-elevated #111721` | action rows, panels |
| `--story-gold #bca374` | authority rule, selected marker, `◆ DETERMINISTIC` stamp |
| `--story-gold-soft` | authority surface tint |
| `--accent-primary #7c6cf2` | custom action accent, supplement inset |
| `--accent-soft` | custom action focus glow |
| `--status-success` | `allowed` chip |
| `--status-warning` | `allowed_with_cost`, `requires_clarification`, stale |
| `--status-error` | `blocked`, branch archived |
| `--status-info` | `checking`, `previewed` |
| `--border-subtle` | hairline dividers, row separators |
| `--border-strong` | selected row rule, focus ring base |
| `--text-primary` | headings, intent |
| `--text-secondary` | body, display_text |
| `--text-muted` | costs, risks, ids, limitations |
| `--font-editorial` | intent, situation headings |
| `--font-body` | controls, display_text, status labels |
| `--font-mono` | ids, counters, reason codes, fingerprints |
| `--radius-sm` | chips |
| `--radius-md` | rows, panels |

### 12.2 Minimal new tokens (proposed, not created in 0D4-C-P)

These alias existing palette values; they do **not** introduce new
colors.  Production 0D4-C may add them to `design-system.css`:

```css
--nt-authority-rule: var(--story-gold);
--nt-supplement-inset: var(--accent-soft);
--nt-row-selected-rule: var(--story-gold);
--nt-status-allowed: var(--status-success);
--nt-status-cost: var(--status-warning);
--nt-status-clarify: var(--accent-primary);
--nt-status-blocked: var(--status-error);
--nt-stale-veil: rgba(255, 255, 255, 0.04);
```

Rationale: the 0D3A token inventory already recommends
`--review-authority` / `--review-supplement` / `--review-conflict` /
`--review-stale` aliases.  These `--nt-*` tokens follow the same
discipline, scoped to Narrative Turn semantic roles.

### 12.3 Typography hierarchy

| Element | Font | Size | Weight |
| --- | --- | --- | --- |
| Workspace heading (h1) | editorial | 20px | 600 |
| Section heading (h2) | editorial | 16px | 600 |
| Row intent | editorial | 15px | 500 |
| Display text | body | 14px | 400 |
| Status label | body | 13px | 500 |
| Costs/risks | mono | 12px | 400 |
| Reason code | mono | 12px | 400 |
| Counter | mono | 12px | 500 |
| Audit mark (fingerprint prefix) | mono | 11px | 400 |

### 12.4 Motion vocabulary

`MOTION_INTENSITY: 2–3`.  Three motion primitives only:

1. **Row selection**: gold left rule slides in from top, 120ms
   `ease-out`.  Reduced motion: instant.
2. **Panel reveal**: Feasibility Panel / Preview fade in 160ms
   `ease-out`.  Reduced motion: instant.
3. **Status flash**: primary action success flash 1.5s
   `ease-in-out` (0D4-D only).  Reduced motion: disabled.

No parallax, no shimmer, no staggered card entrance, no auto-scroll.

### 12.5 Focus treatment

- Gold 2px `:focus-visible` outline (existing 0D3A rule).
- Focus ring offset 2px.
- Custom Action Composer focus: violet ring (supplement accent).
- Focus restoration: after Context Navigator change, focus moves to
  the workspace `h1`.

## 13. Responsive behavior

| Breakpoint | Layout | Evidence Rail | Action rows |
| --- | --- | --- | --- |
| ≥1280px | 3-column (sidebar / main / rail) | right column | vertical stack |
| 900–1279px | 2-column (sidebar / main); rail below Feasibility | stacked below | vertical stack |
| 760–899px | single column; rail collapsed | "查看依据" disclosure | vertical stack |
| ≤759px | single column, priority order | collapsed | vertical stack |

Touch targets ≥40px on all breakpoints.  No horizontal scroll at any
width.  `min-width: 0` on all flex/grid children (per 0D3A RC2 rule).

## 14. Accessibility

| Requirement | Implementation |
| --- | --- |
| Heading hierarchy | one `h1` (workspace); `h2` per region; `h3` per row |
| Landmarks | Simulator Shell already has `<main id="dashboard-view">`; workspace mounts as `<section id="narrative-turn-workspace" role="region" aria-labelledby="nt-heading">` (no nested `<main>`); `<aside>` evidence rail; `<section>` per region with `aria-labelledby` |
| Radiogroup | native `<fieldset>` + `<legend>` + `<input type="radio">` per row (no `role="radio"`/`aria-checked` on rows); browser-native arrow-key + Space behavior |
| Keyboard | native radio `↑`/`↓`/`←`/`→` traverse rows; `Space` selects; `Tab` regions; `Esc` blurs composer |
| Focus-visible | gold 2px outline on all interactive elements |
| Focus restoration | after context switch, focus → workspace `h1` |
| Loading announcement | `aria-live="polite"` in Turn Status Notice |
| Error | Turn Status Notice switches from `role="status"` + `aria-live="polite"` to `role="alert"` + `aria-live="assertive"`; **no other component has `role="alert"`** |
| Live region | Turn Status Notice is the **only** business live region; **no other component (FeasibilityPanel, ConsequencePreview, CustomAction counter) has `aria-live`** |
| Non-color | every status has icon + Chinese label |
| Contrast | WCAG AA on all text; status chips tested with `--text-primary` on `--bg-elevated` |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` disables all 3 motion primitives |
| Counter SR | counter is plain text via `aria-describedby` on the textarea; **no `aria-live` on counter**; threshold crossings announced once via Turn Status Notice |
| Unavailable reason | `data-unavailable="true"` on row + `aria-describedby` referencing always-visible reason text; **no `aria-disabled`**; radio remains natively selectable; **not** `title`-only; no hover required |
| Stale response | no focus move; no announcement; previous result retained; stale action groups use native `disabled` |
| Context switch | focus → workspace `h1`; `aria-live` announces `上下文已就绪` |

## 15. HTTP Wire Contract (binding spec for 0D4-C)

This phase does **not** implement API calls.  The following is the
binding spec for 0D4-C production implementation.

### 15.1 HTTP methods

| Endpoint | Method | Body |
| --- | --- | --- |
| `/api/narrative-turn/context` | `GET` | none (query params: project_id, timeline_id, branch_id, chapter_id, source_version_id) |
| `/api/narrative-turn/plan` | `GET` | none (query params: project_id, timeline_id, branch_id, chapter_id, source_version_id) |
| `/api/narrative-turn/feasibility` | `POST` | request body (see §15.3) |
| `/api/narrative-turn/preview` | `POST` | request body (see §15.4) |

All four endpoints return `Cache-Control: no-store` and must not be
cached by browsers or proxies.

### 15.2 Context response (GET /api/narrative-turn/context)

```json
{
  "schema_version": "1.0",
  "scope": {
    "project_id": "project-slug",
    "timeline_id": "timeline-slug",
    "branch_id": "branch-slug"
  },
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "context_fingerprint": "abc123...",
  "canon_revision": "rev_abc",
  "planner_revision": "narrative-turn-planner-v1",
  "branch": {
    "lifecycle": "open",
    "activity": "active",
    "narrative_state_data": "available"
  },
  "situation": {
    "chapter_goal": "字符串或 null",
    "active_conflicts": ["字符串数组"],
    "characters": ["字符串数组"],
    "locations": ["字符串数组"],
    "resources": ["字符串数组"],
    "world_rules": ["字符串数组"],
    "open_threads": ["字符串数组"],
    "time_window": "字符串或 null",
    "dependencies": ["字符串数组"]
  },
  "evidence_codes": ["SOURCE_VERSION_BOUND", "CANON_REVISION_BOUND"],
  "limitations": []
}
```

Notes:
- `branch.lifecycle`: `"open"` or `"archived"` (from `snapshot.branch_open`)
- `branch.activity`: `"active"` or `"inactive"` (from `snapshot.branch_is_active`)
- `branch.narrative_state_data`: `"available"`, `"unavailable"`, `"scope_mismatch"`, or `"invalid"`
- `context_fingerprint` is NOT used in URL; it is used only for request binding and freshness validation
- All enum values are strings; all tuples are arrays; no Python method names are exposed
- Empty/missing fields use `null` or `[]`; never omit a field

### 15.3 Plan response (GET /api/narrative-turn/plan)

```json
{
  "schema_version": "1.0",
  "turn_id": "turn_abc123",
  "scope": {
    "project_id": "project-slug",
    "timeline_id": "timeline-slug",
    "branch_id": "branch-slug"
  },
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "context_fingerprint": "abc123...",
  "planner_revision": "narrative-turn-planner-v1",
  "recommended_actions": [
    {
      "action_id": "action_xyz",
      "action_type": "advance",
      "display_text": "调查迷雾森林中失踪旅人的下落",
      "intent": "推进主线目标",
      "expected_costs": [{"key": "time", "level": "high"}, {"key": "resource", "level": "medium"}],
      "expected_risks": [{"key": "safety", "level": "high"}],
      "unavailable_reasons": [],
      "deterministic_order": 1
    }
  ],
  "custom_action_policy": {
    "max_length": 200,
    "forbidden_patterns": [],
    "feasibility_pipeline": []
  }
}
```

Notes:
- Exactly 3 `recommended_actions` guaranteed by contract
- `expected_costs`/`expected_risks` are arrays of `{"key": "...", "level": "..."}` objects, NOT tuples of pairs
- `turn_id` is derived deterministically from the context fingerprint and planner revision

### 15.4 Feasibility request body (POST /api/narrative-turn/feasibility)

For recommended action:
```json
{
  "project_id": "project-slug",
  "timeline_id": "timeline-slug",
  "branch_id": "branch-slug",
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "expected_context_fingerprint": "abc123...",
  "action_source": "recommended",
  "selected_action_id": "action_xyz"
}
```

For custom action:
```json
{
  "project_id": "project-slug",
  "timeline_id": "timeline-slug",
  "branch_id": "branch-slug",
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "expected_context_fingerprint": "abc123...",
  "action_source": "custom",
  "custom_action_text": "自定义行动文本内容"
}
```

Custom text security rules:
- Raw text exists only in the current HTTPS/local request body
- Never enters URL, localStorage, file system, or access logs
- Never echoed in response
- Backend returns only SHA-256 hash
- Frontend retains text only in textarea memory state

### 15.5 Feasibility response

```json
{
  "schema_version": "1.0",
  "validation_id": "val_abc123",
  "turn_id": "turn_abc123",
  "context_fingerprint": "abc123...",
  "action_source": "recommended",
  "selected_action_id": "action_xyz",
  "custom_action_text_hash": null,
  "status": "allowed_with_cost",
  "blocking_reasons": ["RESOURCE_COST_HIGH"],
  "cost_explanation": [{"key": "resource", "level": "high"}],
  "risk_explanation": [{"key": "safety", "level": "high"}],
  "checked_at": "2026-07-25T12:00:00Z"
}
```

Notes:
- `status` is one of: `"allowed"`, `"allowed_with_cost"`, `"requires_clarification"`, `"blocked"`
- These are successful responses, NOT HTTP transport errors

### 15.6 Preview request body (POST /api/narrative-turn/preview)

Backend **never** trusts client-provided Validation DTO.  Instead:
1. Re-bind context from request params
2. Validate `expected_context_fingerprint`
3. Rebuild Plan
4. Re-execute feasibility
5. Generate Preview

For recommended action:
```json
{
  "project_id": "project-slug",
  "timeline_id": "timeline-slug",
  "branch_id": "branch-slug",
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "expected_context_fingerprint": "abc123...",
  "action_source": "recommended",
  "selected_action_id": "action_xyz"
}
```

For custom action:
```json
{
  "project_id": "project-slug",
  "timeline_id": "timeline-slug",
  "branch_id": "branch-slug",
  "chapter_id": 1,
  "source_version_id": "manual_v003",
  "expected_context_fingerprint": "abc123...",
  "action_source": "custom",
  "custom_action_text": "自定义行动文本内容"
}
```

### 15.7 Preview response

```json
{
  "schema_version": "1.0",
  "preview_id": "prev_abc123",
  "turn_id": "turn_abc123",
  "context_fingerprint": "abc123...",
  "preview_fingerprint": "def456...",
  "action_source": "recommended",
  "selected_action_id": "action_xyz",
  "custom_action_text_hash": null,
  "validation_status": "allowed_with_cost",
  "reason_codes": [],
  "expected_costs": [{"key": "resource", "level": "high"}],
  "expected_risks": [{"key": "safety", "level": "high"}],
  "likely_consequences": ["可能导致...", "或将..."],
  "evidence_codes": ["SOURCE_VERSION_BOUND"],
  "limitations": ["BRANCH_STATE_UNAVAILABLE"],
  "generated_at": "2026-07-25T12:00:00Z"
}
```

### 15.8 Error envelope

All error responses follow this structure:

```json
{
  "error": {
    "code": "CONTEXT_STALE",
    "message": "上下文已过期，请重新规划。",
    "request_id": null
  }
}
```

HTTP status codes:

| Code | Semantics |
| --- | --- |
| `400` | Malformed request (missing/invalid params) |
| `404` | Explicit scope/source not found |
| `409` | Stale context/source/canon/turn/action |
| `422` | Deterministic feasibility input rejected (ACTION_TOO_LONG, ACTION_UNPARSEABLE) |
| `500` | Safe internal error (never includes raw exception, traceback, or absolute paths) |

**Never** return:
- Raw exception
- Traceback
- Absolute filesystem paths
- Custom action raw text
- Provider information

### 15.9 Request and race condition spec

| Scenario | Spec |
| --- | --- |
| Parent context change (project/timeline/branch/chapter/source) | `AbortController.abort()`; `storyosRequestGeneration += 1`; discard in-flight responses |
| Generation mismatch on response | silently ignore; do not render; do not announce |
| New selection | previous feasibility/preview marked stale; new request issued |
| Recommended vs custom mutual selection | selecting one clears the other's "active" selection; stale-response guard on the cleared result |
| URL sync | every selection updates URL query (see §16); `popstate` re-renders from URL |
| Back/Forward | `popstate` re-binds context from URL; stale in-flight requests aborted |
| Explicit 404 | render error boundary; do **not** fall back to default project; retain URL |
| Stale response | never displayed as latest; previous valid result retained until fresh arrives |

## 16. URL state spec

```
?mode=simulator
&view=narrative-turn
&project_id={project_id}
&timeline_id={timeline_id}
&branch_id={branch_id}
&chapter_id={chapter_id}
&source_version_id={source_version_id|""}
&turn_id={turn_id|""}
&action_id={action_id|""}
```

### 16.1 Parameter rules

| Parameter | Required | Derivable | Trust |
| --- | --- | --- | --- |
| `mode` | yes | no | must equal `simulator` for this workspace |
| `view` | yes | no | must equal `narrative-turn` |
| `project_id` | yes | no | validated against `/api/projects` |
| `timeline_id` | yes | no | validated against context navigator |
| `branch_id` | yes | no | validated against branch registry |
| `chapter_id` | yes | no | validated against chapter list |
| `source_version_id` | no | defaults to current | validated against version list |
| `turn_id` | no | derived from plan | re-bind current context → deterministically rebuild `NarrativeTurnPlan` → verify URL `turn_id` == rebuilt `plan.turn_id` (see §16.4; **not** validated against any Turn store) |
| `action_id` | no | derived from selection | verified to be one of the three `action_id` values in the rebuilt plan |

### 16.4 Turn ID authority (0D4-C, no persisted Plan)

Phase 0D4-C does **not** persist `NarrativeTurnPlan` and does **not**
read from `NarrativeTurnStore`.  The URL `turn_id` is therefore
verified by deterministic rebuild, not by store lookup:

```
1. Re-bind current context (project/timeline/branch/chapter/source)
   → NarrativeTurnContextSnapshot
2. Deterministically rebuild NarrativeTurnPlan via the 0D4-B planner
3. If URL has no turn_id:
     use the rebuilt plan.turn_id as the current turn
4. If URL turn_id == rebuilt plan.turn_id:
     restore the matching action selection from URL action_id
5. If URL turn_id != rebuilt plan.turn_id:
     enter stale/invalid state; do NOT auto-correct the URL;
     do NOT read NarrativeTurnStore; do NOT call append_plan;
     do NOT create a Plan record
```

`action_id` (if present) must be one of the three `action_id` values
in the rebuilt plan.  A mismatch enters the same stale/invalid state
without auto-correction.

### 16.2 Forbidden in URL

- Custom action raw text (never; only SHA-256 hash exists in
  Feasibility/Preview responses; never persisted; never URL-encoded;
  raw text exists only in request body and textarea memory state)
- Full `context_fingerprint` (never; only used for request binding;
  never appears in URL or DOM `title`)
- Provider prompts, responses, credentials.

### 16.3 Custom action text security

Raw custom action text has the following security constraints:
- Never enters URL query parameters
- Never stored in localStorage or any persistent storage
- Never written to filesystem
- Never logged in access logs or error traces
- Never echoed in any response
- Never exposed in DOM (only hash is shown)
- Backend returns only SHA-256 hash
- Frontend retains text only in textarea memory state during current session
- Internal reason-code dumps (only structured user text in DOM).

### 16.4 Scope mismatch handling

If URL `project_id`/`timeline_id`/`branch_id` does not match the
server-bound scope, the workspace renders an `上下文无效` blocking
state.  It does **not** auto-correct the URL.  The user must
re-navigate via the Context Navigator.

## 17. Forbidden anti-patterns

| Anti-pattern | Why forbidden |
| --- | --- |
| Three-column "skill card" grid for actions | reads as game UI, not editorial desk |
| Chat-window custom action input | implies conversational AI; violates non-execution contract |
| Multiple equal-weight primary buttons | violates single-primary-action rule |
| Color-only status | fails accessibility; violates 0D3A rule |
| Hover-only cost/risk revelation | hides decision-critical info |
| Large red banner for blocking states | violates "restrained, no large red" rule |
| Novel-prose preview styling | misleads user that preview is canonical text |
| Full fingerprint in URL/DOM | leaks audit data; violates §16.2 |
| Raw JSON dump in Situation region | fails "no JSON dump" rule (§5.3) |
| Fuzzy status labels (`也许可以`) | violates feasibility engine's 4-status discipline |
| Autocomplete on custom action | implies LLM assist, which is `default: no` |
| "确认该结果" on preview | preview is read-only |
| Marketing hero block | violates editorial-desk direction |
| Neon/glass/gradient-as-content | violates 0D3A direction |

## 18. Implementation file map (for 0D4-C, not this phase)

| File | Responsibility | Phase |
| --- | --- | --- |
| `web/templates/index.html` | add `<section id="narrative-turn-workspace" role="region" aria-labelledby="nt-heading">` inside Simulator Shell (no nested `<main>`) | 0D4-C |
| `web/static/simulator-narrative-turn.js` | new module; URL parse, context bind, render, stale guard | 0D4-C |
| `web/static/simulator-narrative-turn.css` | new stylesheet; reuses design-system.css tokens; adds `--nt-*` aliases | 0D4-C |
| `web/routes.py` (or new `narrative_turn_routes.py`) | **0D4-C read-only endpoints only**: `/api/narrative-turn/context`, `/api/narrative-turn/plan`, `/api/narrative-turn/feasibility`, `/api/narrative-turn/preview` — these call the sealed 0D4-B pure-compute services only | 0D4-C |
| `web/static/simulator-context-navigator.js` | extend to emit `branch_id` in context-ready event | 0D4-C |
| `web/static/design-system.css` | add `--nt-*` token aliases (minimal) | 0D4-C |

**0D4-C-P does not create or modify any of these files.**  This map is
authoritative for the next phase only.

### 18.1 API phase boundary (0D4-C vs 0D4-E)

The read-only Narrative Turn routes in `web/routes.py` (or
`web/narrative_turn_routes.py`) belong to **Phase 0D4-C**.  They are
**not** part of Phase 0D4-E.

```
0D4-C owns (read-only, pure-compute):
  - GET  /api/narrative-turn/context   → ContextWireDTO
  - GET  /api/narrative-turn/plan      → PlanWireDTO
  - POST /api/narrative-turn/feasibility → ValidationWireDTO (request body with scope + action selection)
  - POST /api/narrative-turn/preview   → PreviewWireDTO (request body with scope + action selection)
```

These endpoints:
- may only call the **sealed 0D4-B** pure-compute services
  (`NarrativeTurnContextBinder.bind()`,
  `NarrativeTurnPlanner.build_plan()`,
  `NarrativeActionFeasibility.validate_recommended()` /
  `validate_custom()`, `NarrativeTurnPreviewService.preview()`);
- must **not** call `NarrativeTurnStore.append_*`;
- must **not** generate `NarrativeTurnResult`;
- must **not** append any `NarrativeTurnTransition`;
- must **not** write branch state, Canon, Chroma, or NarrativeMemory;
- must **not** confirm a Turn;
- must **not** call the Provider.

```
0D4-E owns (branch mutation + retrieval isolation):
  - branch create / select / archive / restore endpoints
  - branch-aware NarrativeMemory migration
  - retrieval isolation
  - Chroma branch filter / re-index
```

The 0D4-C read-only Narrative Turn routes are **not** reserved for
0D4-E; they are part of 0D4-C's production implementation.

## 19. Acceptance checklist (cross-reference)

| Question | Answer | Section |
| --- | --- | --- |
| How does the workspace embed in the Simulator Shell? | New section inside Simulator mode, reusing sidebar/topbar/navigator | §3 |
| How are 3 recommended actions compared clearly? | Vertical decision list, same row anatomy, always-visible costs/risks | §6 |
| How is custom action mutually exclusive with recommended? | Selecting one clears the other's active selection; feasibility reflects current source | §7.4 |
| How are 4 feasibility statuses distinguished? | Label + color + icon + enabled/disabled; never color-only | §8.1 |
| How are evidence/cost/risk/limitation layered? | Authority/advisory/unavailable tiers; separate blocks in Feasibility Panel; rail for evidence | §5, §8.2 |
| How does preview avoid being mistaken for fact? | Hedged verbs; `预计后果（定性）` heading; no novel-prose styling | §9 |
| How does primary action appear with no confirm service? | `确认服务尚未接入` always disabled in 0D4-C | §10.2 |
| How will 0D4-D enable confirmation? | 7 conditions in §10.3; blocked/clarification always disable | §10.3 |
| How does context switch prevent stale response? | AbortController + generation counter + silent discard | §15 |
| How do URL/Back/Forward sync? | URL query params; `popstate` re-binds; no auto-correct on mismatch | §16 |
| How do keyboard/SR users operate? | Radiogroup, focus-visible, focus restoration, live region, role=alert | §14 |
| How do narrow desktop/mobile degrade? | Rail collapses; rows stay vertical; priority order on mobile | §13 |
| Which existing tokens/components are reused? | All `--bg-*`, `--story-gold`, `--accent-primary`, `--status-*`, `--font-*`, `--radius-*` | §12.1 |
| Which minimal new tokens are needed? | 8 `--nt-*` aliases (no new colors) | §12.2 |
| Which real files need changes in implementation? | 6 files listed in §18 | §18 |
