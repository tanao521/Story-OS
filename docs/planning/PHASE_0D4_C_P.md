# Phase 0D4-C-P — Narrative Turn Workspace Frontend Design Preflight

> Phase: 0D4-C-P
> Title: Narrative Turn Workspace — Frontend Design Preflight & Production-Ready Interaction Specification
> Status: **SEALED** (after 0D4-C-P-FV2)
> Date: 2026-07-25

## 1. Phase state

```
Phase 0D4-P: PASSED
Phase 0D4-A: SEALED
Phase 0D4-B-FIX-RC-FV: PASSED
Phase 0D4-B: SEALED
Phase 0D4-C-P-FIX-RC: SUPERSEDED BY FIX-RC2
Phase 0D4-C-P-FIX-RC2: ACCEPTED
Phase 0D4-C-P-FIX-RC2-FV: SUPERSEDED BY FV2
Phase 0D4-C-P-FV2: PASSED
Phase 0D4-C-P: SEALED
Phase 0D4-C production implementation: NOT ENTERED
Phase 0D4-D: NOT ENTERED
Phase 0D4-E: NOT ENTERED
Phase 0D4-F: NOT ENTERED
```

This phase produced **design specifications only**.  No production UI,
routes, API, Provider, Canon, Chroma, NarrativeMemory, branch
lifecycle, NarrativeTurnStore, or real project data was modified.

The follow-up `0D4-C-P-FIX-RC` phase corrected contract drift
(component count, branch dimensions, native radio semantics, real
snapshot field binding, single live region, visible disabled reason).
The `0D4-C-P-FIX-RC2` phase further corrected:
- Explicit HTTP Wire DTO schema for all four endpoints
- HTTP method conventions (GET for context/plan, POST for feasibility/preview)
- Error envelope structure
- Single Live Region enforcement (only TurnStatusNotice)
- Unavailable radio semantics (no `aria-disabled`, use `data-unavailable` + `aria-describedby`)
- Custom action text security (raw text never enters URL/localStorage/logs)
- Document status markers updated

## 2. Scope

| In scope | Out of scope |
| --- | --- |
| Read existing 0D4-A/B authority docs | Modify production UI code |
| Read existing Simulator Shell frontend | Add production routes |
| Read 0D3A/0D3B1 visual direction | Wire API endpoints |
| Invoke `frontend-design` Skill | Confirm or persist Turn |
| Produce UI specification | Create React/Vue components |
| Produce interaction state matrix | New third-party dependencies |
| Produce component contract | Network access |
| Update implementation brief | Git add/commit/push/reset/clean/stash/rebase |
| Optional isolated prototype (skipped — see §8) | Enter Phase 0D4-C production |

## 3. Mandatory workflow compliance

| Step | Required by §3 | Status |
| --- | --- | --- |
| 1. Find and read `frontend-design` Skill | yes | ✅ Skill loaded; Design Read completed |
| 2. Complete Design Read per Skill | yes | ✅ Aesthetic direction committed (refined editorial restraint, per Skill + OWNER-locked 0D3A) |
| 3. Audit existing Simulator Shell | yes | ✅ `index.html`, `simulator-context-navigator.js`, `simulator-panel-review.js`, `app.js` audited |
| 4. Audit 0D3A/0D3B1 visual direction | yes | ✅ `simulator_visual_direction.md`, `simulator_css_token_inventory.md`, `simulator_wireframes.md`, `simulator_component_spec.md`, `simulator_responsive_accessibility_spec.md`, `simulator_frontend_architecture_audit.md`, `simulator_review_state_matrix.md` audited |
| 5. Audit 0D4-A/B data contracts | yes | ✅ `simulator_narrative_turn_architecture.md`, `simulator_narrative_turn_contract_map.md`, `simulator_narrative_turn_state_machine.md`, `simulator_narrative_turn_planner.md`, `simulator_action_feasibility.md`, `PHASE_0D4_A.md`, `PHASE_0D4_B.md` audited |
| 6. Produce Narrative Turn workspace plan | yes | ✅ 3 design docs + this phase doc + delivery report |

## 4. Deliverables produced

| Document | Path | Purpose |
| --- | --- | --- |
| UI Specification | [docs/design/simulator_narrative_turn_ui_spec.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_ui_spec.md) | Visual system, layout, regions, accessibility, URL state, anti-patterns |
| Interaction State Matrix | [docs/design/simulator_narrative_turn_interaction_states.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_interaction_states.md) | All UI states per region, transitions, DOM contract, live region matrix |
| Component Contract | [docs/design/simulator_narrative_turn_component_contract.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_component_contract.md) | 10 components (Workspace, SituationHeader, EvidenceSummary, ActionGroup, ActionRow, Composer, FeasibilityPanel, Preview, PrimaryAction, StatusNotice), responsibilities, DOM selectors, forbidden behaviors, test contract |
| Phase Planning (this doc) | [docs/planning/PHASE_0D4_C_P.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_C_P.md) | Phase scope, workflow compliance, deliverables, acceptance |
| Delivery Report | [docs/planning/PHASE_0D4_C_P_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_C_P_DELIVERY_REPORT.md) | Evidence, audit results, safety boundaries, conclusion |
| Implementation Brief update | [docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md) | Status markers updated |

## 5. Design decisions

### 5.1 Aesthetic direction: refined editorial restraint

The `frontend-design` Skill pushes for bold aesthetic differentiation.
The OWNER-locked 0D3A direction ("Night editorial desk / evidence
rail") and the Phase 0D4-C-P §6 constraint ("延续现有 Simulator 视觉
语言，不创建另一套产品") override pure-aesthetic maximalism.

The aesthetic commitment is **refined editorial restraint**, executed
with the precision the Skill demands: typographic hierarchy, hairline
rhythm, gold authority marks, and a single decisive motion vocabulary.
No new font, no new palette, no new motion system.

### 5.2 Recommended action layout: vertical decision list

Three recommended actions are rendered as a vertical list of comparable
rows, not a three-column card grid.  Rationale:

- Matches editorial-desk metaphor (marked-up decision sheet, not skill
  palette)
- Keeps all three options readable on narrow screens
- Always-visible costs/risks (no hover-only revelation)
- Avoids game-UI connotation

### 5.3 Custom action: violet inset, not chat window

Custom Action Composer uses a hairline inset with violet accent
(`--accent-primary`, the existing supplement color) to signal "your
input, not deterministic output".  No chat-window styling (no bubble,
no avatar, no send arrow) — violates the non-execution contract.

### 5.4 Primary action: always disabled in 0D4-C

The primary action is `确认服务尚未接入`, always disabled, never
faking success.  This is the honest representation of the current
phase (0D4-B sealed; 0D4-D confirm service not yet implemented).

### 5.5 Evidence Rail: continuation of 0D3A audit rail

The right-hand Evidence Rail is the same 0D3A audit rail, now
populated with Turn evidence, costs, risks, and reason codes.  No new
column system.

### 5.6 No isolated prototype

Per Phase 0D4-C-P §22: "截图不是封版硬门槛。不要为了浏览器截图
反复消耗时间和额度."  The `frontend-design` Skill was used to
produce the design specification; an isolated prototype was determined
**not necessary** because:

1. The visual direction is already locked by 0D3A and validated in
   0D3B1/0D3C1 production code.
2. The component contract provides DOM-level testable selectors (§15
   of component contract).
3. The interaction state matrix provides exhaustive state coverage
   (§12 of interaction states).
4. A prototype would duplicate existing 0D3A patterns without adding
   new design information.

The `prototypes/phase0d4c/` directory is therefore **not created**.
This is a deliberate decision, not an omission.

## 6. Acceptance checklist (per §24)

| # | Question | Answer | Evidence |
| --- | --- | --- | --- |
| 1 | How does the workspace embed in the Simulator Shell? | New section inside Simulator mode, reusing sidebar/topbar/navigator | UI spec §3 |
| 2 | How are 3 recommended actions compared clearly? | Vertical decision list, same row anatomy, always-visible costs/risks | UI spec §6 |
| 3 | How is custom action mutually exclusive with recommended? | Selecting one clears the other's active selection; feasibility reflects current source | UI spec §7.4, states §8.3 |
| 4 | How are 4 feasibility statuses distinguished? | Label + color + icon + enabled/disabled; never color-only | UI spec §8.1 |
| 5 | How are evidence/cost/risk/limitation layered? | Authority/advisory/unavailable tiers; separate blocks in Feasibility Panel; rail for evidence | UI spec §5, §8.2 |
| 6 | How does preview avoid being mistaken for fact? | Hedged verbs; `预计后果（定性）` heading; no novel-prose styling; defensive verb check | UI spec §9, contract §9.1 |
| 7 | How does primary action appear with no confirm service? | `确认服务尚未接入` always disabled in 0D4-C | UI spec §10.2 |
| 8 | How will 0D4-D enable confirmation? | 7 conditions in UI spec §10.3; blocked/clarification always disable | UI spec §10.3, states §7.3 |
| 9 | How does context switch prevent stale response? | AbortController + generation counter + silent discard | UI spec §15, states §8.4–8.5 |
| 10 | How do URL/Back/Forward sync? | URL query params; `popstate` re-binds; no auto-correct on mismatch | UI spec §16 |
| 11 | How do keyboard/SR users operate? | Native radio group (`<fieldset>`+`<legend>`+`<input type="radio">`), focus-visible, focus restoration, single business live region, role=alert, visible disabled reason via `aria-describedby` | UI spec §14 |
| 12 | How do narrow desktop/mobile degrade? | Rail collapses; rows stay vertical; priority order on mobile | UI spec §13 |
| 13 | Which existing tokens/components are reused? | All `--bg-*`, `--story-gold`, `--accent-primary`, `--status-*`, `--font-*`, `--radius-*` | UI spec §12.1 |
| 14 | Which minimal new tokens are needed? | 8 `--nt-*` aliases (no new colors) | UI spec §12.2 |
| 15 | Which real files need changes in implementation? | 6 files listed in UI spec §18 | UI spec §18 |

All 15 questions answered.

## 7. Safety boundaries

| Boundary | Status |
| --- | --- |
| Production UI code changes | 0 |
| Production route changes | 0 |
| Provider calls | 0 |
| Network | 0 |
| Real tokens/cost | 0 |
| Canon writes | 0 |
| Chroma writes | 0 |
| NarrativeMemory writes | 0 |
| NarrativeTurnStore writes | 0 |
| Branch lifecycle writes | 0 |
| Real project data writes | 0 |
| New dependencies | 0 |
| Git write operations | 0 |

## 8. Isolated prototype decision

**Not created.**  See §5.6 above.  The design is fully specified in
the 3 design documents with DOM-level testable contracts.  A prototype
would consume time and tokens without adding new design information,
which violates Phase 0D4-C-P §22 guidance.

## 9. Phase conclusion

```
Phase 0D4-C-P-FIX-RC: SUPERSEDED BY FIX-RC2
Phase 0D4-C-P-FIX-RC2: ACCEPTED
Phase 0D4-C-P-FIX-RC2-FV: SUPERSEDED BY FV2
Phase 0D4-C-P-FV2: PASSED
Phase 0D4-C-P: SEALED
Phase 0D4-C production implementation: NOT ENTERED
```

Phase 0D4-C production implementation requires separate OWNER
authorization.  This phase does not authorize it.

The follow-up `0D4-C-P-FIX-RC` phase corrected design-contract drift
(component count 9 → 10; Custom Composer states 14 → 15; URL `turn_id`
authority; real `NarrativeTurnContextSnapshot` field binding; 3 branch
dimensions; native radio semantics; single business live region;
visible `aria-describedby` disabled reason; vertical decision list
terminology; API phase boundary 0D4-C vs 0D4-E).  Phase 0D4-C-P:
SEALED after Phase 0D4-C-P-FV2.

Stop.  Do not enter Phase 0D4-C production.
