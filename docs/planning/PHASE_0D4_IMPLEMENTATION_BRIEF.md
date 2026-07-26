# Phase 0D4 Implementation Brief

> Phase 0D4-P output.  Authorizes **nothing**.  Each sub-phase requires
> separate OWNER authorization.

## Current authorization

- Phase 0D4-P: **PASSED** (this document)
- Phase 0D4-A: **SEALED** (implementation complete; FIX-RC2-FV verified)
- Phase 0D4-B-FIX-RC: **ACCEPTED** (6 closure issues verified)
- Phase 0D4-B-FIX-RC-FV: **PASSED** (4 fact-verification issues locked)
- Phase 0D4-B: **SEALED** (124 focused tests + 214 regression tests pass)
- Phase 0D4-C-P-FIX-RC: **SUPERSEDED BY FIX-RC2**
- Phase 0D4-C-P-FIX-RC2: **ACCEPTED** (HTTP Wire DTO, GET/POST method conventions, error envelope, single Live Region enforcement, unavailable radio semantics, custom text security)
- Phase 0D4-C-P-FIX-RC2-FV: **SUPERSEDED BY FV2** (fact verification: old contract scan complete, all 18 rules pass)
- Phase 0D4-C-P-FV2: **PASSED** (final authority closure: 22 rules pass, all old contract residues removed)
- Phase 0D4-C-P: **SEALED** after Phase 0D4-C-P-FV2 (frontend-design Skill used; 3 design docs produced; design-contract drift corrected)
- Phase 0D4-C: **SEALED** (production workspace + read-only API bridge implemented; 243 focused tests + 431 related regression tests pass; 674 tests executed in total; all security boundaries at 0)
- Phase 0D4-C-RC1: **ACCEPTED WITH RC2/RC3 CLOSURE** (real browser runtime acceptance, JS syntax verification, security sentinel audit, endpoint no-diff audit, AbortController integration audit, warning inventory, correct test arithmetic; all security boundaries at 0)
- Phase 0D4-C-RC2: **ACCEPTED WITH RC3 CLOSURE** (Context Navigator reintegration, isolated-fixture browser E2E, workspace visibility fix, delivery report fact correction; all security boundaries at 0)
- Phase 0D4-C-RC3: **PASSED** (full isolated-fixture browser E2E 75-item checklist, RC3 security sentinel, RC3 zero-write audit, Context Navigator integration tests, branch selector fix, state-missing branch fixture; all security boundaries at 0)
- Phase 0D4-D: **PASSED** (transactional Turn confirmation, idempotent operation replay, first-writer-wins concurrency, forward recovery, branch-local event journal, branch-local state projection, 22 focused tests + 483 regression tests pass; all security boundaries at 0)
- Phase 0D4-E: **NOT ENTERED**
- Phase 0D4-F: **NOT ENTERED**

## Global constraints (all sub-phases)

- Production Live: DEFAULT-OFF
- Canary: NOT AUTHORIZED
- Real Provider calls: 0
- Real tokens / cost: 0
- No new dependencies
- No `git add/commit/push/reset/clean/stash` unless explicitly authorized
- No bypass of `ChapterCommitService` for chapter finalization
- No bypass of `vector_index_lifecycle` for Chroma indexing in branch scenarios
- No Reader Persona / model output treated as Canon authority
- No UI redesign without `frontend-design` skill for 0D4-C

## Phase 0D4-A — Narrative Turn contracts, state machine, append-only store

**Goal:** Land the data contracts and a deterministic, offline, append-only
Turn store with no UI and no Canon write.

**Scope (as implemented):**
- `core/contracts/narrative_turn.py` — `TimelineContext`, `NarrativeScope`, `NarrativeTurnPlan`, `NarrativeActionOption`, `NarrativeCustomActionPolicy`, `NarrativeActionValidation`, `NarrativeTurnResult`, `NarrativeBranch`, `NarrativeTurnTransition`
- `system/narrative_turn_store.py` — append-only store with path containment, atomic write (reuse `ProviderUsageReconciliationStore` pattern), idempotency, transition journal
- `system/narrative_branch_store.py` — branch registry with create/select/archive/restore (store-level only)
- State machine enforcement in store layer
- Temporary-project tests only

**OWNER Decisions Applied:**
- `TimelineContext` independent of `ProjectContext`
- `NarrativeScope` combines project_id + timeline_id + branch_id for all scope binding
- Branch `lifecycle_status` ("open"/"archived") separated from `active_branch_id` in registry
- Immutable records + append-only transition journal replaces in-place status updates
- Plan creation is a non-canonical write (not read-only)
- Validation scope fields completed (schema_version, validation_id, turn_id, scope, chapter_id, context_fingerprint)

**Allowed:**
- New production code (contracts + stores)
- New tests
- `python -m compileall`
- `pytest` focused

**NOT allowed:**
- Provider calls
- UI changes
- Canon writes
- Branch migration of existing data
- Chroma writes
- Branch mutation API endpoints (create/select/archive/restore — reserved for 0D4-E)
- Real branch migration (reserved for 0D4-E)
- Read-only Narrative Turn API endpoints (context/plan/feasibility/preview — reserved for 0D4-C, not 0D4-A)

**Test gate:**
- Contract validation (all field types, enums, immutability)
- Store path containment (reuse B1-FIX escape tests as template)
- Store atomic write + idempotency
- State machine legal/illegal transitions
- Branch registry operations

**Stop condition:** All focused tests pass; no Provider/network/token; no
Canon write; compile clean.

**Phase 0D4-A Status:** **SEALED** (FIX-RC2-FV verified)

## Phase 0D4-B — Context binding, 3 deterministic recommended actions, custom action feasibility, read-only preview

**Goal:** Deterministic Turn plan creation with 3 recommended actions and
a feasibility pipeline for custom actions.  Read-only preview; no confirmation.

**Scope (as implemented):**
- `system/narrative_turn_context.py` — Context Binder: binds `ProjectContext` + timeline + branch + chapter + source + canon revision into a frozen `NarrativeTurnContextSnapshot` with deterministic `context_fingerprint`. Cold-start read-only (no file writes). Deep-immutable (recursive `_freeze`). Strict canonical serialization (no `default=str`). Branch-state isolation (branch-scoped path only).
- `system/narrative_turn_planner.py` — Deterministic Planner: generates exactly 3 recommended actions from structured evidence, with stable IDs and deterministic ordering
- `system/narrative_action_feasibility.py` — 14-step feasibility pipeline for both recommended and custom actions; custom action normalization (NFKC, control char rejection, length limit, SHA-256 hashing)
- `system/narrative_turn_preview.py` — Read-only qualitative preview service (no writes, no Provider, no Canon)
- `core/contracts/narrative_turn_preview.py` — Preview DTO + fingerprint utility
- 124 focused tests in `tests/test_phase0d4b_narrative_turn_planner.py` (85 original + 26 FIX-RC + 13 FIX-RC-FV)

**Implementation details:**
- Context fingerprint uses SHA-256 of strict canonical JSON (no `default=str`) over 18 authority inputs: planner_revision, project_id, timeline_id, branch_id, chapter_id, source_version_id, source_fingerprint, canon_revision, planning_revision, chapter_plan_revision, dependency_revision, branch_state_revision, world_revision, character_revision, location_revision, resource_revision, relationship_revision, time_state_revision
- Deep immutability: all dict/list fields recursively frozen via `_freeze()` (dicts → sorted tuples of pairs, lists → tuples); accessor methods return fresh deep copies
- Cold-start read-only: `bind()` uses `_read_json_file`/`_read_text_file` only; never calls `load_planning`, `RevisionService.active_canon`, `load_versions_index`, or `_create_registry_if_missing`
- Branch state isolation: reads only `data/narrative_memory/state/{timeline_id}/{branch_id}/current.json`; legacy flat path never used
- Planner revision: `narrative-turn-planner-v1`
- 8 candidate categories derived from structured evidence (goal/investigate/risk/protect/negotiate/retreat/breakthrough/sacrifice)
- Exactly 3 actions guaranteed, with unique intent + at least 2 different action types
- Action ID = sha256(planner_revision : context_fingerprint : normalized_intent : action_type : deterministic_order)[:16]
- Feasibility pipeline fixed order: input → scope → source freshness → branch status → structure → world rules → canon → capability → resource → location → time → relationship → dependency → cost
- 4 status levels: blocked > requires_clarification > allowed_with_cost > allowed
- Preview is qualitative only, with explicit limitations, no canonical language

**Allowed:**
- Read-only access to existing planning/canon/world/character data
- New production code (context binder + planner + feasibility + preview)
- New tests
- New preview contract DTO

**NOT allowed:**
- Provider calls (deterministic only)
- UI changes
- Canon writes
- Branch lifecycle writes
- Modifying existing planning data
- Calling NarrativeTurnStore.append_plan() / append_validation()
- HTTP route changes

**Test gate:**
- Context binding (project/timeline/chapter/source/canon mismatch detection)
- Exactly 3 recommended actions, stable ids, deterministic order
- Unavailable options kept with reasons
- Custom action: empty/oversize/unparseable/world-conflict/capability/resource/location/time/canon-conflict
- Classification: allowed / allowed_with_cost / requires_clarification / blocked
- Same input → same output (reproducibility)
- Read-only: no store writes, no Result, no Transition

**Stop condition:** All focused tests pass; feasibility never returns fuzzy
"maybe"; no Provider; no Canon write; no NarrativeTurnStore append.

**Phase 0D4-B Status:** **SEALED** (124 focused tests + 214 regression tests pass; 0D4-B-FIX-RC ACCEPTED; 0D4-B-FIX-RC-FV PASSED)

## Phase 0D4-C — Production Simulator UI

**Goal:** Add the Narrative Turn workspace to the existing Simulator Shell.

**Mandatory pre-condition:** Invoke the `frontend-design` skill to produce
a formal interaction and visual spec before any UI code.

**Preflight status:** Phase 0D4-C-P: **SEALED** after Phase 0D4-C-P-FV2.
The `frontend-design` Skill was invoked; Design Read completed.  Three
design documents produced:
- [simulator_narrative_turn_ui_spec.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_ui_spec.md) — visual system, layout, regions, accessibility, URL state, anti-patterns
- [simulator_narrative_turn_interaction_states.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_interaction_states.md) — all UI states per region, transitions, DOM contract
- [simulator_narrative_turn_component_contract.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_component_contract.md) — 10 components, DOM selectors, forbidden behaviors, test contract

**Production status (Phase 0D4-C):** **PASSED**.  The production
workspace and read-only API bridge are implemented.  See
[PHASE_0D4_C.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_C.md)
and [PHASE_0D4_C_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_C_DELIVERY_REPORT.md).

**Scope:**
- `web/static/simulator-narrative-turn.js` — new module
- `web/templates/index.html` — new workspace section inside Simulator Shell (no nested `<main>`)
- `web/static/simulator-narrative-turn.css`
- `web/routes.py` (or new `web/narrative_turn_routes.py`) — **read-only** API endpoints (0D4-C owns these, **not** 0D4-E):
  - `GET /api/narrative-turn/context` → Wire DTO (see UI spec §15.2)
  - `GET /api/narrative-turn/plan` → Wire DTO (see UI spec §15.3)
  - `POST /api/narrative-turn/feasibility` → Wire DTO (see UI spec §15.5); request body (§15.4)
  - `POST /api/narrative-turn/preview` → Wire DTO (see UI spec §15.7); request body (§15.6)
- Reuse `storyosApiGet/Post`, `AbortController`, generation counter, context navigator
- URL state: `mode=simulator&view=narrative-turn&branch_id=...&turn_id=...`

**API phase boundary (0D4-C vs 0D4-E):**
- **0D4-C owns (read-only, pure-compute):** the 4 Narrative Turn
  endpoints above.  These may only call the sealed 0D4-B pure-compute
  services.  They must NOT call `NarrativeTurnStore.append_*`, must NOT
  generate `NarrativeTurnResult`, must NOT append `Transition`, must
  NOT write branch state / Canon / Chroma / NarrativeMemory, must NOT
  confirm a Turn, must NOT call the Provider.
- **0D4-E owns (branch mutation + retrieval isolation):** branch
  create / select / archive / restore endpoints, branch-aware
  NarrativeMemory migration, retrieval isolation, Chroma branch
  filter / re-index.  See §Phase 0D4-E below.

The read-only Narrative Turn routes are **not** reserved for 0D4-E;
they are part of 0D4-C's production implementation.

**URL `turn_id` authority (0D4-C, no persisted Plan):**
Phase 0D4-C does **not** persist `NarrativeTurnPlan` and does **not**
read from `NarrativeTurnStore`.  The URL `turn_id` is verified by
deterministic rebuild:
1. Re-bind current context → `NarrativeTurnContextSnapshot`
2. Deterministically rebuild `NarrativeTurnPlan` via the 0D4-B planner
3. If URL has no `turn_id`: use the rebuilt `plan.turn_id` as current
4. If URL `turn_id` == rebuilt `plan.turn_id`: restore action selection
5. If URL `turn_id` != rebuilt `plan.turn_id`: enter stale/invalid
   state; do NOT auto-correct the URL; do NOT read NarrativeTurnStore;
   do NOT call `append_plan`; do NOT create a Plan record.

`action_id` (if present) must be one of the three `action_id` values
in the rebuilt plan.

**UI flow:**
```
Situation display
→ 3 recommended action rows in a vertical decision list
→ custom action input
→ feasibility result (inline)
→ consequence preview (inline)
→ explicit confirm button (single primary action, always disabled in 0D4-C)
```

**NOT allowed:**
- New page (must be workspace in existing shell)
- React/Vue/new build system
- Provider calls
- Canon writes
- Multiple equal-weight primary actions
- Branch mutation endpoints (reserved for 0D4-E)
- `turn_id` validation against `NarrativeTurnStore` (use deterministic rebuild)
- Faking confirm success before 0D4-D

**Test gate:**
- JavaScript syntax check
- DOM contract tests (reuse 0D3B1/0D3C1 patterns)
- Stale-response guard
- AbortController on parent context change

**Stop condition:** UI renders the flow; no Provider; no Canon write;
frontend-design spec followed.

**Phase 0D4-C Status:** **PASSED** (243 focused tests + 431 related
regression tests pass; 674 tests executed in total; all security
boundaries at 0; production workspace implemented; read-only API bridge
implemented; turn confirmation NOT implemented).

**Phase 0D4-C-RC1 Status:** **ACCEPTED WITH RC2/RC3 CLOSURE** (real
browser runtime acceptance, JS syntax verification via `node --check`,
security sentinel audit, endpoint no-diff audit, AbortController
integration audit, warning inventory, correct test arithmetic; all
security boundaries at 0).

**Phase 0D4-C-RC2 Status:** **ACCEPTED WITH RC3 CLOSURE** (Context
Navigator reintegration, isolated-fixture browser E2E, workspace
visibility fix, delivery report fact correction; all security
boundaries at 0).

**Phase 0D4-C-RC3 Status:** **PASSED** (full isolated-fixture browser
E2E 75-item checklist, RC3 security sentinel, RC3 zero-write audit,
Context Navigator integration tests, branch selector fix,
state-missing branch fixture; all security boundaries at 0;
Phase 0D4-C: SEALED).

## Phase 0D4-D — Turn confirm, branch-local event log, state delta, recovery

**Goal:** Wire confirmation to an immutable Turn record + branch-local
event log + state delta proposal, with idempotency and recovery.

**Scope:**
- `system/narrative_turn_service.py` — confirm endpoint with `operation_id`, atomic write, idempotent replay
- Branch-local event log append (reuse `ProviderUsageReconciliationStore` atomic pattern)
- State delta projection (extend `NarrativeMemoryService` with branch awareness)
- Recovery: detect partial write, re-project deterministic state delta

**Allowed:**
- Branch-local writes (Turn records, event log, state delta)
- New tests

**NOT allowed:**
- Canon writes
- Provider calls
- Chroma writes (branch-local events are not indexed yet)

**Test gate:**
- Duplicate POST (same operation_id) → idempotent
- Concurrent POST (different operation_id) → first wins
- Stale context / source / canon / branch → correct error code
- Partial write recovery
- State delta reproducibility

**Stop condition:** All focused tests pass; no Canon write; no Provider.

## Phase 0D4-E — Branch create/switch/archive, retrieval isolation

**Goal:** Full branch lifecycle and Chroma retrieval isolation.

**API phase boundary (owned by 0D4-E, NOT 0D4-C):**
- branch create / select / archive / restore endpoints
- branch-aware NarrativeMemory migration endpoints
- retrieval-isolation query endpoints
- Chroma branch filter / re-index endpoints

The read-only Narrative Turn routes (context / plan / feasibility /
preview) belong to **0D4-C**, not 0D4-E.  The earlier wording "所有
API endpoints reserved for 0D4-E" was over-wide and is superseded by
this explicit split.

**Scope:**
- Branch create/switch/archive/restore endpoints
- `NarrativeMemoryService` migration to branch-aware paths
- `memory_repair_service.py` migration from legacy `vector_memory.build_or_update_index` to `vector_index_lifecycle`
- Static guard test forbidding legacy vector API in new code
- Branch-aware Chroma query filter

**Allowed:**
- Branch registry writes
- Migration of legacy event files (copy, not move)
- Chroma re-index via `vector_index_lifecycle`

**NOT allowed:**
- Auto-merge
- Canon writes
- Provider calls

**Test gate:**
- Branch A events not in branch B
- Inactive branch not in retrieval
- Archived branch not in active state
- Branch switch preserves old branch
- Restore re-indexes correctly
- Uncommitted Turn does not enter long-term Canon memory
- Legacy vector API guard test

**Stop condition:** All focused tests pass; no cross-branch leakage; no
Canon write.

## Phase 0D4-F — Chapter compilation wiring

**Goal:** Wire confirmed Turn records → chapter compilation candidate →
existing `ChapterCommitService` (no bypass).

**Scope:**
- `system/narrative_chapter_compiler.py` — reads confirmed Turns in branch, produces a chapter candidate version (not a commit)
- Candidate version written via existing `VersionManager` / manual version path
- `ChapterCommitService.commit_chapter()` called with the candidate `source_version_id` (existing entry, no new commit channel)
- append `included_in_chapter` transition
  → append `committed` transition after `ChapterCommitService` succeeds
- Turn record itself stays **immutable**; lifecycle facts live exclusively
  in the append-only transition journal (never as flags on the Turn record)

**Allowed:**
- Writing candidate version via existing version manager
- Calling existing `ChapterCommitService`
- New tests

**NOT allowed:**
- New commit channel
- Bypassing quality check / review gate
- Direct Canon write
- Provider calls

**Test gate:**
- Compile reads only confirmed Turns
- Blocked/cancelled/superseded Turns ignored
- Stable order
- Source changed → compile blocked
- Compile ≠ commit
- Commit routes through existing entry
- Canon updated only via `RevisionService`

**Stop condition:** All focused tests pass; no new commit channel; Canon
updated only via existing `ChapterCommitService`.

## Cross-phase test matrix (cumulative)

| Test category | 0D4-A | 0D4-B | 0D4-C | 0D4-D | 0D4-E | 0D4-F |
| --- | --- | --- | --- | --- | --- | --- |
| Context binding | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Recommended actions (3, stable, deterministic) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Custom action feasibility | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Preview (read-only) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Confirmation idempotency | — | — | — | ✓ | ✓ | ✓ |
| Branch isolation | — | — | — | — | ✓ | ✓ |
| Chapter compile (no bypass) | — | — | — | — | — | ✓ |
| Path containment (B1-FIX pattern) | ✓ | — | — | ✓ | ✓ | — |
| Atomic write (B1-FIX pattern) | ✓ | — | — | ✓ | ✓ | — |
| State machine transitions | ✓ | — | — | ✓ | — | ✓ |

## Development environment and model

**统一开发环境：** TRAE Work CN / SOLO Coder / 单 Agent / 当前可用默认或最强编码模型 / 推理强度仅在界面支持时设置

| Phase | Reasoning intensity | Rationale |
| --- | --- | --- |
| 0D4-A | medium | contract + store; deterministic |
| 0D4-B | medium-high | feasibility rules; many edge cases |
| 0D4-C | medium | UI; requires frontend-design skill first |
| 0D4-D | medium-high | idempotency/recovery; safety-critical |
| 0D4-E | high | isolation; security-critical |
| 0D4-F | medium | wiring; reuse existing entry |
