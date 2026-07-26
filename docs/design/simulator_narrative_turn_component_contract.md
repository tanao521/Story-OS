# Simulator Narrative Turn — Component Contract

> Phase 0D4-C-P preflight artifact.  **No production UI code is changed
> by this document.**
>
> Authority: this contract defines the production-implementable
> component decomposition for the Narrative Turn workspace.  It is the
> binding spec for Phase 0D4-C implementation.  Components are vanilla
> JS modules + DOM renderers (no React/Vue) — the existing Simulator
> Shell technology stack.

## 1. Component tree

```
NarrativeTurnWorkspace (root)
├── NarrativeSituationHeader
├── NarrativeEvidenceSummary
├── RecommendedActionGroup
│   └── RecommendedActionRow × 3
├── CustomActionComposer
├── FeasibilityPanel
├── ConsequencePreview
├── TurnPrimaryAction
└── TurnStatusNotice (live region, sibling of header)
```

**Component count: 10** (Workspace, SituationHeader,
EvidenceSummary, ActionGroup, ActionRow, Composer, FeasibilityPanel,
Preview, PrimaryAction, StatusNotice).

Components are **not** classes — they are render functions following
the existing `simulator-panel-review.js` pattern: `function renderX(target, data)`.
State is held in module-scoped variables in `simulator-narrative-turn.js`,
not in component instances.

## 2. NarrativeTurnWorkspace

| Field | Value |
| --- | --- |
| Responsibility | Mount the workspace; own URL parsing, context binding, request lifecycle, generation counter, AbortController; render child components in order; restore focus on context switch |
| Required data | `scope` (project_id, timeline_id, branch_id), `chapter_id`, `source_version_id`, optional `turn_id`, `action_id` |
| States | `initial`, `loading`, `ready`, `incomplete`, `stale`, `error`, `explicit_404` (see interaction states §2) |
| Emitted events | `storyos:narrative-turn-context-ready` (CustomEvent, detail = scope+chapter+source); `storyos:narrative-turn-action-selected` (detail = action_source + id/hash) |
| Consumed events | `storyos:panel-context-ready` (from Context Navigator); `popstate` (URL); `storyos:dashboard-ready` |
| Accessibility semantics | `<section id="narrative-turn-workspace" role="region" aria-labelledby="nt-heading">`; one `h1`.  The Simulator Shell (`index.html`) already contains `<main id="dashboard-view">`; the workspace MUST NOT nest a second `<main>`. |
| Stale behavior | on parent context change: `AbortController.abort()`; `generation += 1`; clear child selections; set `data-context-state="loading"` |
| Loading behavior | render skeleton children; `aria-busy="true"` on the workspace section |
| Error behavior | render error boundary; announcement via TurnStatusNotice; retain URL |
| CSS responsibility | workspace grid layout; responsive collapse; `data-context-state` attribute selectors |
| Forbidden | computing feasibility status; storing raw custom text; calling Provider; writing to any store; rendering full fingerprint; nesting another `<main>` |

### 2.1 DOM contract

```html
<section id="narrative-turn-workspace"
         role="region"
         aria-labelledby="nt-heading"
         data-context-state="ready|loading|stale|error|incomplete|explicit_404"
         aria-busy="true|false">
  <h1 id="nt-heading">叙事回合 · 第 N 章</h1>
  <!-- child components mount here -->
</section>
```

**Landmark audit evidence:** `story-os-demo/web/templates/index.html`
already contains three `<main>` elements (`setup-view`,
`project-center-view`, `dashboard-view`).  The workspace therefore
mounts as `<section role="region">` to avoid a nested `<main>`.

## 3. NarrativeSituationHeader

| Field | Value |
| --- | --- |
| Responsibility | Render project/timeline/branch/chapter/source/canon/freshness/branch dimensions/planner-revision as escaped chips; never show full fingerprint.  Branch status is rendered as **three independent** dimensions (Lifecycle / Activity / Narrative State Data), never a single "branch state" chip. |
| Required data | `ContextWireDTO` fields: `scope`, `chapter_id`, `source_version_id`, `canon_revision`, `context_fingerprint` (prefix only), `branch.lifecycle`, `branch.activity`, `branch.narrative_state_data`, `planner_revision` |
| States | per UI spec §4.2 (9 header states) + 3 branch dimension overlays (Lifecycle / Activity / Narrative State Data — interaction states §2.1.1–2.1.3) |
| Emitted events | none (display only) |
| Accessibility semantics | `<header class="nt-situation-header" aria-labelledby="nt-context-heading">` (with a visible `h2 id="nt-context-heading"` inside).  Does **not** use `role="banner"` — the page-level banner landmark is owned by the Simulator Shell topbar, not by this subregion.  Equivalent acceptable form: `<section class="nt-situation-header" role="region" aria-label="叙事回合上下文">`.  Chips are `<span>` with `title`. |
| Stale behavior | show amber `已过期` chip; do not clear other chips |
| Loading behavior | chips render as `—` placeholders |
| Error behavior | show red-amber `上下文错误` chip; details in TurnStatusNotice |
| CSS responsibility | chip layout; gold rule on `◆ DETERMINISTIC` stamp; `data-state` attribute selectors per chip |
| Forbidden | full fingerprint display; auto-correcting URL; rendering provider prompts; `role="banner"` on this subregion; collapsing the 3 branch dimensions into one chip |

### 3.1 DOM contract

```html
<header class="nt-situation-header" aria-labelledby="nt-context-heading">
  <h2 id="nt-context-heading" class="nt-situation-title">叙事回合上下文</h2>
  <span class="nt-chip nt-chip-project" title="项目">…</span>
  <span class="nt-chip nt-chip-timeline" title="时间线">…</span>
  <span class="nt-chip nt-chip-branch"
        data-branch-lifecycle="open|archived" title="分支生命周期">…</span>
  <span class="nt-chip nt-chip-branch-activity"
        data-branch-activity="active|inactive" title="分支激活指针">…</span>
  <span class="nt-chip nt-chip-branch-state"
        data-branch-state="available|unavailable|scope_mismatch|invalid"
        title="分支叙事状态数据">…</span>
  <span class="nt-chip nt-chip-chapter" title="章节">第 N 章</span>
  <span class="nt-chip nt-chip-source" title="源版本">…</span>
  <span class="nt-chip nt-chip-canon" title="Canon 修订（8 字符前缀）">…</span>
  <span class="nt-chip nt-chip-freshness" data-freshness="fresh|stale" title="上下文新鲜度">…</span>
  <span class="nt-chip nt-chip-planner" title="规划器修订">narrative-turn-planner-v1</span>
  <span class="nt-deterministic-stamp" aria-hidden="true">◆ DETERMINISTIC</span>
</header>
```

**Branch dimension mapping (binding to ContextWireDTO):**

| Dimension | `data-*` attribute | Values | Wire DTO source | Server-side source |
| --- | --- | --- | --- | --- |
| Lifecycle | `data-branch-lifecycle` | `open` / `archived` | `context.branch.lifecycle` | `snapshot.branch_open` (`NarrativeBranch.lifecycle_status`) |
| Activity | `data-branch-activity` | `active` / `inactive` | `context.branch.activity` | `snapshot.branch_is_active` / registry `active_branch_id` |
| Narrative State Data | `data-branch-state` | `available` / `unavailable` / `scope_mismatch` / `invalid` | `context.branch.narrative_state_data` | `branch_state_revision` + `BRANCH_STATE_*` limitations |

`data-branch-lifecycle="archived"` is a **blocking** state and must surface the `branch_archived` overlay (never `branch_state_unavailable`, which is advisory-only on the Narrative State Data dimension).

## 4. NarrativeEvidenceSummary

| Field | Value |
| --- | --- |
| Responsibility | Render the current narrative situation (goal, conflicts, characters, locations, resources, world rules, threads, time window) in 3 tiers (authority/advisory/unavailable), plus the `limitations` list.  Browser data source is `ContextWireDTO` — see §12.1 for server-side source contract. |
| Required data | `ContextWireDTO` fields: `context.situation.chapter_goal`, `context.situation.active_conflicts`, `context.situation.characters`, `context.situation.locations`, `context.situation.resources`, `context.situation.world_rules`, `context.situation.open_threads`, `context.situation.time_window`, `context.situation.dependencies`, `context.evidence_codes`, `context.limitations` |
| States | collapsed (default), expanded (on "查看依据" toggle) |
| Emitted events | none (display only) |
| Accessibility semantics | `<section aria-labelledby="nt-situation-heading">`; "查看依据" is `<button aria-expanded="false" aria-controls="nt-evidence-detail">` |
| Stale behavior | render with stale veil (`data-stale="true"`); do not clear |
| Loading behavior | skeleton lines per field |
| Error behavior | n/a (evidence is part of context; error handled at workspace level) |
| CSS responsibility | 3-tier visual hierarchy (gold rule / violet inset / hairline grey); disclosure animation |
| Forbidden | dumping raw JSON; fabricating missing fields; mixing tiers; rendering reader persona as authority; referencing a `.evidence` field that does not exist on the snapshot; treating `evidence_codes`/`limitations` as `string[]` |

### 4.1 Field binding table (authoritative)

| Display field | Wire DTO field | Server-side source (for reference, not browser API) | Tier | Empty / missing / invalid handling |
| --- | --- | --- | --- | --- |
| 当前章节目标 | `context.situation.chapter_goal` | `chapter_plan_dict()` → goal | authority | `PLANNING_DATA_MISSING`/`CHAPTER_PLAN_MISSING` → `未提供` |
| 当前冲突 | `context.situation.active_conflicts` | `narrative_state_dict()` → active_conflicts | authority | empty array → `未提供` |
| 角色与位置 | `context.situation.characters`, `context.situation.locations` | `character_data_dict()` + `world_data_dict()` → locations | authority | `CHARACTER_DATA_MISSING` / `WORLD_DATA_MISSING` → `未提供` |
| 可用资源 | `context.situation.resources` | `character_data_dict()` / `world_data_dict()` → resources | authority | missing → `未提供` |
| 世界规则约束 | `context.situation.world_rules` | `world_data_dict()` → rules / taboos | authority | `WORLD_DATA_INVALID` → `数据无效` |
| 未解决线索 | `context.situation.open_threads` | `rolling_window_dict()` → open threads | advisory | `ROLLING_WINDOW_MISSING` → `未提供` (advisory) |
| 时间窗口 | `context.situation.time_window` | `narrative_state_dict()` → time window | authority | empty → `未提供` |
| 前置依赖 | `context.situation.dependencies` | `dependencies_dict()` | advisory | `DEPENDENCIES_MISSING` → `未提供` (advisory) |
| 规划元数据 | `context.situation.*` (from wire DTO) | `planning_data_dict()` | advisory | `PLANNING_DATA_SPARSE` → `数据稀疏` note |
| 已知限制 | `context.limitations` | `limitations: tuple[str, ...]` | authority (limitation list) | empty array → render no list, not `None` |
| 证据代码 | `context.evidence_codes` | `evidence_codes: tuple[str, ...]` | authority (audit) | empty array → render no codes |

### 4.2 DOM contract

```html
<section class="nt-evidence-summary" aria-labelledby="nt-situation-heading">
  <h2 id="nt-situation-heading">当前局势</h2>
  <div class="nt-evidence-tier nt-evidence-authority">
    <!-- authority fields bound from chapter_plan_dict() / narrative_state_dict() /
         character_data_dict() / world_data_dict() -->
  </div>
  <div class="nt-evidence-tier nt-evidence-advisory">
    <!-- advisory fields bound from rolling_window_dict() / dependencies_dict() /
         planning_data_dict() -->
  </div>
  <div class="nt-evidence-tier nt-evidence-unavailable">
    <!-- fields whose source limitation is *_MISSING/*_INVALID -->
  </div>
  <button class="nt-disclosure" aria-expanded="false" aria-controls="nt-evidence-detail">查看依据</button>
  <div id="nt-evidence-detail" class="nt-evidence-detail" hidden>
    <!-- source file, revision, fingerprint prefix per evidence code -->
    <ul class="nt-evidence-codes">
      <!-- one <li> per code in context.evidence_codes (string[]) -->
    </ul>
    <ul class="nt-evidence-limitations">
      <!-- one <li> per code in context.limitations (string[]) -->
    </ul>
  </div>
</section>
```

## 5. RecommendedActionGroup

| Field | Value |
| --- | --- |
| Responsibility | Render exactly 3 RecommendedActionRow children; own native radiogroup semantics via `<fieldset>` + `<legend>` + native `<input type="radio">`; clear selection on custom action submit |
| Required data | `PlanWireDTO.recommended_actions` (array of exactly 3 action objects) |
| States | `loading`, `ready`, `stale`, `empty_fallback`, `error` (interaction states §3) |
| Emitted events | `storyos:narrative-turn-action-selected` (detail = `{source: "recommended", action_id, deterministic_order}`) |
| Accessibility semantics | `<fieldset class="nt-action-group" aria-labelledby="nt-actions-heading">` with `<legend>`.  Each row wraps a native `<input type="radio" name="narrative-turn-action">`.  Browser-native arrow-key (`↑`/`↓`/`←`/`→`), `Space` to select, and `Tab` to enter/exit the group apply.  No `role="radiogroup"` / `role="radio"` / `aria-checked` is added on top of the native semantics. |
| Stale behavior | render with stale veil; disable selection; show `重新规划` |
| Loading behavior | 3 skeleton rows |
| Error behavior | single error row; announcement via TurnStatusNotice (**no `role="alert"` on this component**) |
| CSS responsibility | vertical stack layout; row separators; selected gold rule |
| Forbidden | reordering rows; hiding unavailable rows; auto-selecting first; computing status; using `<label role="radio">` without a native radio input; building a custom roving tabindex |

### 5.1 DOM contract

```html
<fieldset class="nt-action-group" aria-labelledby="nt-actions-heading" data-state="ready|loading|stale|error">
  <legend class="nt-action-group-legend" id="nt-actions-heading">推荐行动</legend>
  <!-- RecommendedActionRow × 3 (each row contains a native <input type="radio">) -->
</fieldset>
```

## 6. RecommendedActionRow

| Field | Value |
| --- | --- |
| Responsibility | Render one recommended action: order, type, intent, display_text, costs, risks, status, unavailable reasons; handle selection via the native radio input inside the row `<label>` |
| Required data | `NarrativeActionOption` (all fields); derived `status` (from `unavailable_reasons` + feasibility if requested) |
| States | unselected, selected, unavailable, stale |
| Emitted events | (via parent group) `change` on the native radio |
| Accessibility semantics | `<label class="nt-action-row">` wrapping a native `<input type="radio" name="narrative-turn-action" value="{action_id}">`.  Selection state is carried by the native `checked` property; do **not** duplicate it with `aria-checked`.  Keyboard navigation (`↑↓←→ Space Tab`) is provided by the browser.  Unavailable rows use `data-unavailable="true"` on the row + `aria-describedby` on the radio pointing to visible reason text; **no `aria-disabled`** — radio remains natively selectable for inspection. Confirm button is guarded by backend feasibility authority. |
| Stale behavior | render with stale veil; native `disabled` on all radios in the group |
| Loading behavior | skeleton (handled by parent) |
| Error behavior | n/a (handled by parent) |
| CSS responsibility | row anatomy; gold left rule on selected (`:checked`); status chip; cost/risk mono pairs |
| Forbidden | hover-only cost/risk; color-only status; game-mechanic icons; computing feasibility; using `<label role="radio">` without a native radio input; custom roving tabindex |

### 6.1 DOM contract

```html
<label class="nt-action-row"
       data-selected="false" data-unavailable="false" data-order="1">
  <input type="radio" name="narrative-turn-action" value="action-1"
         class="nt-action-radio" data-action-id="action-1">
  <span class="nt-action-order" aria-hidden="true">①</span>
  <span class="nt-action-type">advance</span>
  <span class="nt-action-intent">推进主线目标</span>
  <span class="nt-action-display">调查迷雾森林中失踪旅人的下落</span>
  <span class="nt-action-costs">time·high · resource·medium</span>
  <span class="nt-action-risks">safety·high</span>
  <span class="nt-action-status" data-status="available|cost|clarify|blocked|pending">可用</span>
  <span class="nt-action-unavailable-reason" hidden>…</span>
</label>
```

For an unavailable row, the radio remains natively selectable (**no** `aria-disabled`). The `data-unavailable="true"` attribute marks the state for CSS, and `aria-describedby` associates the radio with the visible reason text. Confirmation is always blocked by backend feasibility authority:

```html
<label class="nt-action-row" data-unavailable="true" data-order="2">
  <input type="radio" name="narrative-turn-action" value="action-2"
         class="nt-action-radio" data-action-id="action-2"
         aria-describedby="nt-action-2-unavailable">
  <!-- ... -->
  <span id="nt-action-2-unavailable" class="nt-action-unavailable-reason">
    不可用：缺少必要资源
  </span>
</label>
```

`data-selected="true"` is mirrored from the radio's `checked` state on
the `change` event for CSS targeting; it is **not** an accessibility
attribute.

## 7. CustomActionComposer

| Field | Value |
| --- | --- |
| Responsibility | Render textarea + counter + notices + submit; own NFKC normalization + length check + control-char check (client-side preview only; backend is authority); fire feasibility request on submit; clear recommended selection on submit |
| Required data | `NarrativeCustomActionPolicy.max_length` (=200); client-side normalized text; feasibility status (if requested) |
| States | **15 states** per interaction states §4 (idle/editing/validating/too_long/control_char_rejected/unparseable/ambiguous_target/ambiguous_object/allowed/allowed_with_cost/requires_clarification/blocked/checking/superseded_by_recommended/stale_response) |
| Emitted events | `storyos:narrative-turn-action-selected` (detail = `{source: "custom", custom_action_text_hash}`) — note: hash is received from backend response, NOT computed client-side |
| Accessibility semantics | `<section aria-labelledby="nt-custom-heading">`; textarea `aria-label="自定义行动文本"` and `aria-describedby="nt-custom-counter"`; counter is **plain text** (NO `aria-live`); submit `type="button"` (not `type="submit"`).  Threshold crossings (`150/200`, `190/200`, `200/200`, `201/200`) are announced **once** via the single Turn Status Notice live region (§11), never through the counter element. |
| Stale behavior | text retained; `data-state="superseded_by_recommended"`; previous feasibility retained with stale veil |
| Loading behavior | n/a (composer is always interactive unless `too_long`/`control_char_rejected`) |
| Error behavior | feasibility error renders in FeasibilityPanel; composer remains editable |
| CSS responsibility | violet accent inset; counter mono; chip states; focus ring (violet) |
| Forbidden | chat-window styling; autocomplete; persisting raw text to URL/localStorage; computing SHA-256 client-side; submitting on `Enter`; putting `aria-live` on the counter; announcing every keystroke |

### 7.1 DOM contract

```html
<section class="nt-custom-composer" aria-labelledby="nt-custom-heading"
         data-state="idle|editing|validating|too_long|control_char_rejected|unparseable|ambiguous_target|ambiguous_object|allowed|allowed_with_cost|requires_clarification|blocked|checking|superseded_by_recommended|stale_response">
  <h2 id="nt-custom-heading">自定义行动</h2>
  <p class="nt-custom-notice">最多 200 个规范化字符 · 文本仅用于当前可行性分析 · 仅保留 SHA-256 · 不会作为系统命令执行</p>
  <textarea class="nt-custom-input"
            aria-label="自定义行动文本"
            aria-describedby="nt-custom-counter"
            maxlength="400" rows="2"></textarea>
  <span id="nt-custom-counter" class="nt-custom-counter">0/200</span>
  <button class="nt-custom-submit" type="button" disabled>分析可行性</button>
</section>
```

Note: `maxlength="400"` is a safety upper bound on raw input (allows
NFKC expansion); the **authoritative** limit is the normalized length
≤ 200, checked on `input` and on submit.  The counter `<span>` carries
**no** `aria-live`; it is associated with the textarea via
`aria-describedby` so screen readers read it on focus but do not
announce every keystroke.

## 8. FeasibilityPanel

| Field | Value |
| --- | --- |
| Responsibility | Render the 4-status feasibility result with reason text, costs, risks, evidence link, limitations; never compute status |
| Required data | `ValidationWireDTO` fields: `status`, `blocking_reasons`, `cost_explanation`, `risk_explanation`, `context_fingerprint`; selected action source (recommended/custom) |
| States | 8 states per interaction states §5 (absent/loading/allowed/allowed_with_cost/requires_clarification/blocked/stale/error) |
| Emitted events | none (display only) |
| Accessibility semantics | `<section aria-labelledby="nt-feasibility-heading">`; status chip `role="img" aria-label`; reason disclosure `<button aria-expanded>`; **no `aria-live`** |
| Stale behavior | render with stale veil; retain content; primary action disabled |
| Loading behavior | skeleton |
| Error behavior | show error text visibly; announcement via TurnStatusNotice (**no `role="alert"` on this component**) |
| CSS responsibility | status chip colors (via `data-status`); reason/cost/risk separation; disclosure |
| Forbidden | fuzzy labels; `blocked` with confirm button; `requires_clarification` without missing dimension; computing priority |

### 8.1 DOM contract

```html
<section class="nt-feasibility-panel" aria-labelledby="nt-feasibility-heading"
         data-status="absent|loading|allowed|allowed_with_cost|requires_clarification|blocked|stale|error">
  <h2 id="nt-feasibility-heading">可行性分析</h2>
  <span class="nt-feasibility-status" role="img" aria-label="状态：带代价">◇ 带代价</span>
  <div class="nt-feasibility-reasons">
    <p class="nt-feasibility-reason">资源代价较高</p>
    <!-- more reasons -->
  </div>
  <div class="nt-feasibility-costs">
    <h3>代价</h3>
    <ul>
      <li><span class="nt-cost-key">resource</span><span class="nt-cost-level">high</span></li>
    </ul>
  </div>
  <div class="nt-feasibility-risks">
    <h3>风险</h3>
    <ul>
      <li><span class="nt-risk-key">safety</span><span class="nt-risk-level">high</span></li>
    </ul>
  </div>
  <button class="nt-reason-disclosure" aria-expanded="false" aria-controls="nt-reason-codes">查看原始 reason code</button>
  <div id="nt-reason-codes" class="nt-reason-codes" hidden>
    <code>RESOURCE_COST_HIGH</code>
  </div>
</section>
```

## 9. ConsequencePreview

| Field | Value |
| --- | --- |
| Responsibility | Render qualitative preview with hedged language; show freshness + context match; never mimic novel prose; never offer "confirm result" |
| Required data | `PreviewWireDTO` fields: `likely_consequences`, `expected_costs`, `expected_risks`, **`evidence_codes`**, **`limitations`**, `preview_fingerprint`, `generated_at`, `context_fingerprint`.  There is **no** `evidence` field; the audit field is `evidence_codes`. |
| States | 6 states per interaction states §6 (absent/loading/ready/stale/blocked/error) |
| Emitted events | none (display only) |
| Accessibility semantics | `<section aria-labelledby="nt-preview-heading">`; hedging cue `role="img" aria-label="定性预测"`; **no `aria-live`** — ready/stale/error transitions are announced via TurnStatusNotice |
| Stale behavior | render with stale veil (muted, amber rule); `data-stale="true"`; primary action disabled |
| Loading behavior | skeleton with `生成预览中…` |
| Error behavior | show error text visibly; announcement via TurnStatusNotice (**no `role="alert"` on this component**) |
| CSS responsibility | hedged-content styling; stale veil; freshness indicator; **no novel-prose styling** (no drop cap, no justify, no indent) |
| Forbidden | novel-prose styling; "确认该结果" button; unhedged verbs; rendering if context mismatch without stale veil; referencing a `.evidence` field that does not exist on the preview DTO; treating `evidence_codes`/`limitations` as `string[]` |

### 9.1 Hedging defensive check

On render, the component scans the preview text for forbidden verbs
(`已经发生`, `必然`, `将会`, `系统确认`, `注定`).  If any forbidden
verb is found, the component **refuses to render the offending block**
and shows `预览内容异常` instead.  This is a defensive UI guard; the
backend is the primary authority for hedged copy.

### 9.2 DOM contract

```html
<section class="nt-consequence-preview" aria-labelledby="nt-preview-heading"
         data-stale="false|true" data-state="absent|loading|ready|stale|blocked|error">
  <h2 id="nt-preview-heading">预计后果（定性）</h2>
  <span class="nt-preview-freshness" title="预览生成时间与指纹前缀">…</span>
  <span class="nt-preview-context-match" data-match="true|false">上下文匹配|上下文已变更</span>
  <div class="nt-preview-block nt-preview-consequences">
    <h3>可能后果</h3>
    <p>可能导致…</p>
  </div>
  <div class="nt-preview-block nt-preview-costs">
    <h3>预计代价</h3>
    <p>预计…</p>
  </div>
  <div class="nt-preview-block nt-preview-risks">
    <h3>预计风险</h3>
    <p>倾向于…</p>
  </div>
  <div class="nt-preview-evidence-codes">
    <h3>证据代码</h3>
    <!-- one <li> per code in preview.evidence_codes (string[]) -->
  </div>
  <div class="nt-preview-limitations">
    <h3>限制</h3>
    <!-- one <li> per code in preview.limitations (string[]) -->
  </div>
</section>
```

## 10. TurnPrimaryAction

| Field | Value |
| --- | --- |
| Responsibility | Render the single primary action button; manage disabled state per enable-condition matrix; never fake success; in 0D4-C always disabled |
| Required data | selected action (source + id/hash), feasibility status, preview freshness, context freshness, branch lifecycle, source fingerprint, pending request flag |
| States | 0D4-C: `unavailable_in_current_phase` (always); 0D4-D spec: `disabled`, `enabled`, `submitting`, `success`, `collision`, `stale_context`, `recovery_required` (interaction states §7) |
| Emitted events | (0D4-D only) `storyos:narrative-turn-confirm-requested` (detail = `{operation_id, selected_action_id or custom_action_text_hash}`) |
| Accessibility semantics | `<button type="button" class="nt-primary-action" disabled aria-disabled="true" aria-describedby="nt-primary-disabled-reason">`.  The disabled reason is **always visible** as plain text in a sibling `<p id="nt-primary-disabled-reason">` and associated via `aria-describedby`.  The `title` attribute is **not** the sole carrier of the disabled reason; no hover is required to perceive it. |
| Stale behavior | disabled; `aria-describedby` reason text changes to `上下文已过期；请重新规划` (still always visible) |
| Loading behavior | disabled (state managed by parent) |
| Error behavior | disabled; error shown in TurnStatusNotice |
| CSS responsibility | footer-pinned; gold accent when enabled; muted when disabled; spinner when submitting; green-amber flash on success (0D4-D) |
| Forbidden | multiple primary actions; faking success; enabling on `blocked`/`requires_clarification`; enabling on stale preview/context; relying on `title`-only for the disabled reason; hiding the disabled reason behind hover/focus |

### 10.1 DOM contract

```html
<div class="nt-primary-action-container">
  <button type="button" class="nt-primary-action"
          disabled aria-disabled="true"
          aria-describedby="nt-primary-disabled-reason"
          data-state="unavailable_in_current_phase|disabled|enabled|submitting|success|collision|stale_context|recovery_required">
    确认服务尚未接入
  </button>
  <p id="nt-primary-disabled-reason" class="nt-primary-disabled-reason">
    行动确认将在 Phase 0D4-D 接入；当前仅支持规划、分析与预览。
  </p>
</div>
```

In 0D4-C the `data-state` is always `unavailable_in_current_phase`,
the `disabled` and `aria-disabled="true"` are always set, and the
reason `<p>` is always visible.  No confirm event is emitted before
0D4-D.

## 11. TurnStatusNotice

| Field | Value |
| --- | --- |
| Responsibility | Single-line live region for state announcements; the **only** region that announces to screen readers |
| Required data | current status text |
| States | per announcement matrix (interaction states §10) |
| Emitted events | none |
| Accessibility semantics | `<div role="status" aria-live="polite">` for normal; `<div role="alert" aria-live="assertive">` for errors (toggle role) |
| Stale behavior | silent (do not announce stale response) |
| Loading behavior | `读取上下文中…` |
| Error behavior | `role="alert"`; `发生错误：{safe message}` |
| CSS responsibility | single-line; muted; hairline top border; no large banner |
| Forbidden | multiple notice regions; large red banner; announcing stale responses; announcing every counter update |

### 11.1 DOM contract

```html
<div id="nt-status-notice" class="nt-status-notice" role="status" aria-live="polite">
  上下文已就绪
</div>
```

On error, the role toggates:

```html
<div id="nt-status-notice" class="nt-status-notice nt-status-error" role="alert" aria-live="assertive">
  发生错误：{safe message}
</div>
```

## 12. Cross-component data flow

```
Context Navigator
  → emits storyos:panel-context-ready {project_id, timeline_id, branch_id, chapter_id, source_version_id}
  → NarrativeTurnWorkspace receives
  → AbortController.abort(); generation += 1
  → storyosApiGet(/api/narrative-turn/context?...) → ContextWireDTO
  → NarrativeSituationHeader.render(context)
  → NarrativeEvidenceSummary.render(context)    // uses context.situation,
                                                 //   context.evidence_codes,
                                                 //   context.limitations
  → storyosApiGet(/api/narrative-turn/plan?...) → PlanWireDTO
  → RecommendedActionGroup.render(plan.recommended_actions)
  → user selects row OR submits custom
  → emits storyos:narrative-turn-action-selected
  → NarrativeTurnWorkspace receives
  → storyosApiPost(/api/narrative-turn/feasibility, JSON body) → ValidationWireDTO
  → FeasibilityPanel.render(validation)
  → if allowed* : storyosApiPost(/api/narrative-turn/preview, JSON body) → PreviewWireDTO
  → ConsequencePreview.render(preview)
  → TurnPrimaryAction.update(selection, validation, preview, context, branch, source, pending)
  → TurnStatusNotice.announce("可行性分析完成：{status}")
```

### 12.1 Data layer separation

```
Python Domain Contract (server-side only)
  → server-side DTO adapter
  → JSON Wire DTO (HTTP response)
  → JavaScript view model (client-side)
  → DOM renderer
```

Python accessors (`planning_data_dict()`, `chapter_plan_dict()`, `world_data_dict()`,
`character_data_dict()`, `narrative_state_dict()`, `rolling_window_dict()`,
`dependencies_dict()`) are used **only on the server side** to construct
`ContextWireDTO`.  They are **not** browser API methods.

## 13. Forbidden component responsibilities

| Component | Forbidden to |
| --- | --- |
| NarrativeTurnWorkspace | compute feasibility status; store raw custom text; call Provider; write to any store; nest another `<main>` |
| NarrativeSituationHeader | show full fingerprint; auto-correct URL; render provider prompts; use `role="banner"`; collapse the 3 branch dimensions into one chip |
| NarrativeEvidenceSummary | dump raw JSON; fabricate missing fields; mix tiers; treat reader persona as authority; reference a `.evidence` field that does not exist; treat `evidence_codes`/`limitations` as `string[]` |
| RecommendedActionGroup | reorder rows; hide unavailable rows; auto-select first; compute status; use `<label role="radio">` without a native radio input |
| RecommendedActionRow | hover-only cost/risk; color-only status; game icons; compute feasibility; use custom roving tabindex instead of native radio |
| CustomActionComposer | chat styling; autocomplete; persist raw text; compute SHA-256 client-side; submit on Enter; put `aria-live` on the counter |
| FeasibilityPanel | fuzzy labels; blocked with confirm; clarify without dimension; compute priority |
| ConsequencePreview | novel-prose styling; "confirm result" button; unhedged verbs; render on context mismatch without veil; reference a `.evidence` field on the preview DTO |
| TurnPrimaryAction | multiple primary actions; fake success; enable on blocked/clarify; enable on stale; rely on `title`-only for the disabled reason |
| TurnStatusNotice | multiple regions; large banner; announce stale; announce every counter update |

## 14. CSS responsibility boundaries

| Component | Owns | Does NOT own |
| --- | --- | --- |
| NarrativeTurnWorkspace | grid layout; responsive collapse; `data-context-state` selectors | child component internals |
| NarrativeSituationHeader | chip layout; gold rule; stamp | workspace grid |
| NarrativeEvidenceSummary | 3-tier hierarchy; disclosure | chip layout |
| RecommendedActionGroup | vertical stack; row separators | row internals |
| RecommendedActionRow | row anatomy; gold rule on selected; status chip | group layout |
| CustomActionComposer | violet inset; counter; chip states | textarea global styles |
| FeasibilityPanel | status chip colors; reason/cost/risk separation | workspace grid |
| ConsequencePreview | hedged content; stale veil; freshness | workspace grid |
| TurnPrimaryAction | footer pin; gold accent; spinner; flash | workspace grid |
| TurnStatusNotice | single-line; muted; hairline | other regions |

All components MUST use `--nt-*` tokens (UI spec §12.2) or existing
`design-system.css` tokens.  No component may introduce a new color.

## 15. Test contract (for 0D4-C implementation)

Production 0D4-C tests may assert against:

| Assertion target | Selector |
| --- | --- |
| Context state | `#narrative-turn-workspace[data-context-state="ready"]` |
| Action selected | `.nt-action-radio:checked` (native radio `:checked`) — also mirrored on `.nt-action-row[data-selected="true"]` |
| Action unavailable | `.nt-action-row[data-unavailable="true"]`; `.nt-action-radio:not([aria-disabled])`; `.nt-action-radio[aria-describedby]` (radio remains natively selectable for inspection; no `aria-disabled`; backend feasibility is authority) |
| Composer state | `.nt-custom-composer[data-state="too_long"]` |
| Feasibility status | `.nt-feasibility-panel[data-status="blocked"]` |
| Preview stale | `.nt-consequence-preview[data-stale="true"]` |
| Primary disabled | `.nt-primary-action[disabled][aria-disabled="true"][aria-describedby="nt-primary-disabled-reason"]` with visible `#nt-primary-disabled-reason` |
| Live region | `#nt-status-notice[role="status"]` or `[role="alert"]` (the **only** business live region) |
| Counter has no aria-live | `#nt-custom-counter:not([aria-live])` |
| Branch lifecycle | `.nt-chip-branch[data-branch-lifecycle="archived"]` |
| Branch activity | `.nt-chip-branch-activity[data-branch-activity="inactive"]` |
| Branch state data | `.nt-chip-branch-state[data-branch-state="unavailable"]` |

Tests MUST NOT assert against:

- Inline `style` attributes (CSS authority is the stylesheet).
- Class names beyond `.nt-*` (internal classes may change).
- Text content of provider responses (never rendered).
- Full fingerprint values (never in DOM).
- `aria-checked` / `role="radio"` on rows (native radio `:checked` is the authority).
- `title`-only disabled reason on the primary action (it is `aria-describedby`-linked visible text).

## 16. Implementation order (for 0D4-C)

1. `web/static/simulator-narrative-turn.css` — tokens + layout + responsive
2. `web/static/simulator-narrative-turn.js` — workspace root + URL parse + context bind
3. `web/templates/index.html` — mount section inside Simulator Shell
4. `web/static/simulator-context-navigator.js` — extend to emit `branch_id`
5. `web/routes.py` or `web/narrative_turn_routes.py` — read-only API endpoints
6. `web/static/design-system.css` — add `--nt-*` token aliases
7. Tests — DOM contract assertions per §15

Each step is independently testable.  No step may be skipped.
