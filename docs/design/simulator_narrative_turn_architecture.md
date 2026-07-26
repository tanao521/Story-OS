# Simulator Narrative Turn — Architecture Map

> Phase 0D4-P read-only audit artifact.  No production code change.
> Authority: this document reflects the **current** repository state as
> audited in Phase 0D4-P.  It is a design reference, not an implemented
> contract.

## 1. Current architecture map (audited)

### 1.1 Project / Timeline / Canon isolation

| Capability | Current state | File |
| --- | --- | --- |
| `ProjectContext` | frozen dataclass; **project-scoped, no `timeline_id` field** | [core/project_context.py](file:///d:/novel/StoryOS/story-os-demo/core/project_context.py) |
| Active project resolution | explicit root → `.story_os/config.json` `active_project` → cwd | [core/project_context.py](file:///d:/novel/StoryOS/story-os-demo/core/project_context.py#L93) |
| Timeline concept | **metadata only**; UI exposes `timeline_id="main"`, no create/switch/archive API | [web/static/simulator-context-navigator.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-context-navigator.js#L31) |
| Branch concept | **does not exist** in any production code (grep for `branch_id`/`create_branch` returns nothing) | — |
| Canon revision | append-only per-chapter `data/canon_versions/chapter_NNN/` with `active` flag | [system/revision_service.py](file:///d:/novel/StoryOS/story-os-demo/system/revision_service.py#L81) |
| Project isolation in records | `project_id` and `timeline_id` fields exist on panel runs, live audits, reconciliation | [core/contracts/model_persona_panel_execution.py](file:///d:/novel/StoryOS/story-os-demo/core/contracts/model_persona_panel_execution.py#L40), [system/provider_usage_reconciliation.py](file:///d:/novel/StoryOS/story-os-demo/system/provider_usage_reconciliation.py) |

**Gap:** `ProjectContext` carries no `timeline_id`.  All file paths under
`data/` are project-scoped, not timeline-scoped.  A real branch model
would require either (a) timeline-scoped subdirectories, or (b) a
`timeline_id`/`branch_id` field on every record plus query filters.

### 1.2 Chapter / Version / Commit

| Concept | Current state | File |
| --- | --- | --- |
| Source types | `manual`, `edited`, `draft`, `selected` enum | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L30) |
| Version files | `data/{manual,edited,draft}/chapter_NNN_*.json`; selected pointer in `data/versions/chapter_NNN_versions.json` | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L237) |
| Canonical chapter | `data/chapters/chapter_NNN.md` | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L870) |
| Commit entry | `ChapterCommitService.commit_chapter()` with idempotency key, snapshot, rollback, post-commit tasks | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L63) |
| Idempotency | `commit_key = sha256(project_id:chapter_id:source_hash:source_version_id:commit)`; `CommitRunStore` cross-process | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L375) |
| Canon update | `RevisionService.create_and_apply_revision()` inside commit transaction | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py#L554) |
| Atomic write | `DataStore.write_json(backup=True)`; `safe_write` module | [system/data_store.py](file:///d:/novel/StoryOS/story-os-demo/system/data_store.py), [system/safe_write.py](file:///d:/novel/StoryOS/story-os-demo/system/safe_write.py) |

**Reuse verdict:** The commit pipeline is the **single canonical entry**
for chapter finalization.  Narrative Turn chapter compilation MUST route
through `ChapterCommitService`, never bypass it.

### 1.3 Planning system

| Object | Purpose | Reuse for Turn? |
| --- | --- | --- |
| `story_planning.json` (v2.0) | volumes, phases, chapters, plot_threads, character_arcs, foreshadowing, conflicts, climaxes | chapters/plot_threads/foreshadowing are **read inputs** for Turn context |
| `next_chapter_plan.json` | next chapter goal, conflict, climax, characters, world rules | **read input** for Turn context binding |
| `data/planning_control/rolling_window.json` | near/mid/far horizon slots, **preview → confirm → operation_id** pattern | **direct pattern reuse** for Turn preview/confirm |
| `data/planning_control/dependencies.json` | dependency graph, cycle detection | **read input** for feasibility (blocking dependencies) |
| `data/planning_control/narrative_schedules.json` | manual scheduling, revision conflict, replay | **read input**; scheduling service pattern reuse |
| `PlanningControlService` | `save_rolling_window(expected_window_revision, operation_id)`, preview expiry, replay | **direct reuse** for Turn idempotency/recovery |

**Key finding:** `RollingWindowService` already implements the
`preview → confirm → operation_id → revision conflict → replay` pattern.
Narrative Turn should reuse this pattern, not reinvent it.

### 1.4 Evaluation system

| Capability | Read-only? | Authority | File |
| --- | --- | --- | --- |
| `EvaluationService` | writes only to `data/evaluations/` | deterministic aggregators | [evaluation_engine/service.py](file:///d:/novel/StoryOS/story-os-demo/evaluation_engine/service.py) |
| `ReaderSimulatorService` | writes run records | deterministic rules, `EVALUATOR_VERSION="reader-rule-v1"` | [system/reader_simulator.py](file:///d:/novel/StoryOS/story-os-demo/system/reader_simulator.py) |
| `ModelPersonaPanelReviewService` | read-only aggregation | deterministic; model supplements are non-authoritative | [system/model_persona_panel_review_service.py](file:///d:/novel/StoryOS/story-os-demo/system/model_persona_panel_review_service.py) |
| Quality report | stale on source hash change | deterministic | [system/quality_checker.py](file:///d:/novel/StoryOS/story-os-demo/system/quality_checker.py) |

**Authority boundary:**
- **Deterministic** evaluation results (continuity, canon conflict, dependency blockers, character capability from `characters.json`, world rules from `world_bible.json`) → may serve as **feasibility evidence**.
- **Reader Persona** subjective feedback → **must not** be treated as world-state authority.  It is advisory only.
- **Model supplement** (panel run model output) → **must not** bypass deterministic rules.

### 1.5 Memory & retrieval

| Capability | Timeline isolation | File |
| --- | --- | --- |
| `vector_index_lifecycle.index_chapter()` | **yes** — takes `timeline_id`, `canon_revision_id`, `project_id` from context; manifest-enforced | [system/vector_index_lifecycle.py](file:///d:/novel/StoryOS/story-os-demo/system/vector_index_lifecycle.py) |
| `vector_memory.build_or_update_index()` (legacy) | **NO** — no `timeline_id`/`project_id` filter; indexes everything under `data/chapters/` | [system/vector_memory.py](file:///d:/novel/StoryOS/story-os-demo/system/vector_memory.py#L114) |
| `NarrativeMemoryService` | project-scoped only; events keyed by `chapter_id`, no `timeline_id` | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py) |
| `NarrativeMemoryService.extract()` | reads `active_canon(chapter_id)`; produces `unreviewed` candidates | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py#L27) |
| `NarrativeMemoryService.project()` | aggregates `confirmed`/`corrected` events into state buckets | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py#L48) |
| `NarrativeMemoryService.invalidate_from(chapter)` | marks events `active=False` from chapter onward | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py#L69) |

**Critical risk:** `memory_repair_service.py` still calls the legacy
`vector_memory.build_or_update_index()`, which has **no timeline filter**.
This is a Chroma filter bypass vector — see risk matrix.

**Reuse verdict:** `NarrativeMemoryService` already provides
event/state/snapshot/conflict/invalidate semantics.  A confirmed Turn
should produce a `NarrativeMemoryService`-compatible event record
(branch-local), and chapter commit should trigger the existing
`extract()` → `project()` flow.

### 1.6 Web simulator UI

| Element | Current state | File |
| --- | --- | --- |
| Shell | single-page `index.html` with mode buttons (`data-storyos-mode="simulator"`) | [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html#L63) |
| Simulator section | `#simulator-panel-review` with context navigator, panel run planner, live consent | [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html#L168) |
| Context navigator | project/timeline/chapter/source/run selects; URL state; AbortController; stale-response guard | [web/static/simulator-context-navigator.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-context-navigator.js) |
| Panel run planner | Mock-only drawer; Plan → Confirm → Run; duplicate-submit disabled | [web/static/simulator-panel-run.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-panel-run.js) |
| Live consent | dialog; default-off capability; ticket creation only | [web/static/simulator-live-consent.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-live-consent.js) |
| API helper | `storyosApiGet`/`storyosApiPost` with `AbortController`, generation counter | [web/static/app.js](file:///d:/novel/StoryOS/story-os-demo/web/static/app.js#L45) |

**Reuse verdict:** Narrative Turn UI should be a **new workspace inside
the existing Simulator Shell** (not a new page), reusing the context
navigator, `storyosApiGet/Post`, AbortController, and generation-counter
patterns.  A new `simulator-narrative-turn.js` module is the recommended
mount point.

## 2. Reusable capabilities (summary)

| Capability | Reuse for Turn | Condition |
| --- | --- | --- |
| `ProjectContext` + `bind_project_context` | request-scoped project binding | must extend with `timeline_id` for branch isolation |
| `ChapterCommitService` | chapter compilation entry | Turn compile MUST route here |
| `RevisionService` | canon revision creation | only via commit |
| `RollingWindowService` preview/confirm/operation_id pattern | Turn preview/confirm/idempotency | direct pattern reuse |
| `PlanningControlService` | operation log, revision conflict, replay | direct reuse |
| `NarrativeMemoryService` | event record, state projection, invalidate | extend with `branch_id`/`timeline_id` |
| `vector_index_lifecycle` | Chroma indexing with timeline filter | only this API; **never** legacy `vector_memory.build_or_update_index` |
| `ModelPersonaPanelReviewService` | read-only review aggregation | advisory only, not authority |
| `ReaderSimulatorService` | deterministic reader feedback | advisory only |
| `DataStore` + `safe_write` | atomic JSON writes | direct reuse |
| `storyosApiGet/Post` + AbortController + generation | frontend request guard | direct reuse |

## 3. Gaps for Narrative Turn Loop

| Gap | Severity | Notes |
| --- | --- | --- |
| No `timeline_id` on `ProjectContext` | **blocking** | branch isolation impossible without this |
| No branch create/switch/archive API | **blocking** | 0D4-E must add this |
| No `NarrativeTurn`/`NarrativeActionOption`/`NarrativeTurnResult` contracts | **blocking** | 0D4-A must add these |
| No deterministic action feasibility engine | **blocking** | 0D4-B must add this; rules from `world_bible.json`/`characters.json`/`world_rules.json` |
| No branch-local event log | **blocking** | `NarrativeMemoryService` is project-scoped only |
| Legacy `vector_memory.build_or_update_index` has no timeline filter | **high** | must be deprecated/blocked for branch scenarios |
| No Turn → chapter compile wiring | **blocking** | 0D4-F must wire compile through `ChapterCommitService` |
| No Turn UI workspace | **blocking** | 0D4-C must add (after frontend-design skill) |
| No `NarrativeTurnPlan` store | **blocking** | 0D4-A must add append-only store |

## 4. Authority boundaries (final)

| Layer | Authority | Can write Canon? | Can write branch-local state? |
| --- | --- | --- | --- |
| Deterministic rules (world bible, characters, world rules, canon revisions, dependency graph) | **authority** | only via `ChapterCommitService` | no |
| Reader Persona panel | **advisory** | no | no |
| Model supplement (panel run) | **advisory** | no | no |
| User confirmation | **decision** | no (user confirms Turn, not Canon) | yes (creates branch-local Turn record) |
| Branch-local Turn result | **proposed delta** | no | yes (append-only event log) |
| Chapter commit | **canonical** | yes (via `RevisionService`) | no (Canon is global) |

## 5. Data flow (target)

```
Context (project + timeline + chapter + source + canon revision)
  ↓
NarrativeTurnPlan (deterministic, binds context fingerprint)
  ↓
3 recommended actions (deterministic, from planning + world rules + character state)
  + 1 custom action entry
  ↓
Custom action feasibility pipeline (deterministic rules → classification)
  ↓
Preview (read-only; risk/cost projection; no state write)
  ↓
User confirmation (explicit; operation_id; idempotency)
  ↓
Confirmed Turn record (immutable; branch-local event log)
  ↓
Proposed state delta (NarrativeMemoryService-compatible; branch-scoped)
  ↓
... more Turns ...
  ↓
Chapter compilation (reads confirmed Turns in branch)
  ↓
ChapterCommitService.commit_chapter() (existing entry; no bypass)
  ↓
RevisionService.create_and_apply_revision() (Canon update; global)
  ↓
vector_index_lifecycle.index_chapter() (timeline-scoped; only after commit)
```

## 6. Branch isolation strategy (first version)

| Aspect | Strategy |
| --- | --- |
| Storage path | `data/narrative_turns/{timeline_id}/` for Turn records; `data/narrative_memory/events/{timeline_id}/chapter_NNN.json` for branch-local events |
| Metadata | every Turn/event carries `project_id`, `timeline_id`, `branch_id`, `chapter_id`, `source_version_id`, `parent_turn_id` |
| Query filter | all queries MUST filter by `timeline_id` + `branch_id`; no cross-branch reads |
| Chroma filter | `vector_index_lifecycle` only; manifest validates `project_id` + `timeline_id` match |
| Branch activation | explicit user action; only one `active` branch per timeline |
| Archive | branch can be archived (read-only); events remain queryable but not mutable |
| Restore | archived branch can be re-activated; re-index via `vector_index_lifecycle` |
| Merge | **first version: NOT SUPPORTED**; documented as explicit limitation |

## 7. Open questions for OWNER decision

1. **Timeline model:** Should `timeline_id` be added to `ProjectContext`
   (breaking change for all callers), or carried as a separate
   `TimelineContext` bound alongside `ProjectContext`?  Recommend the
   latter to avoid touching every existing call site.

2. **Branch scope:** Should a branch share the same `data/chapters/`
   directory (with branch-scoped canon revisions) or have its own
   `data/branches/{branch_id}/chapters/`?  Recommend the latter for
   isolation.

3. **Custom action LLM assist:** Should the model ever *suggest* custom
   action wording (advisory only, not authority)?  Default: **no** in
   0D4-A/B; revisit after B1 provider pairing is unblocked.

4. **Failure persistence:** Should a "bad ending" Turn produce a
   permanent chapter in the branch, or just a Turn record?  Recommend:
   Turn record only; chapter compilation is always explicit user action.
