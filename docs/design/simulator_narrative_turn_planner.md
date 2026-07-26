# Simulator Narrative Turn Planner — Design Document

> Phase 0D4-B implementation.  Deterministic planner only — no Provider,
> no network, no writes.

## 1. Purpose

The `NarrativeTurnPlanner` generates exactly 3 deterministic recommended
actions for a narrative turn, given a read-only context snapshot.  It is
a pure computation module: no file writes, no store writes, no Provider
calls, no randomness.

## 2. Module layout

| Module | Responsibility | File |
| --- | --- | --- |
| Context Binder | Bind read-only context snapshot, compute fingerprint | [narrative_turn_context.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_context.py) |
| Deterministic Planner | Generate 3 recommended actions from context | [narrative_turn_planner.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_planner.py) |
| Action Feasibility | 14-step validation pipeline for recommended + custom actions | [narrative_action_feasibility.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_action_feasibility.py) |
| Turn Preview | Read-only qualitative consequence projection | [narrative_turn_preview.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_preview.py) |

## 3. Planner revision

```
planner_revision = "narrative-turn-planner-v1"
```

The revision string participates in:
- `context_fingerprint` (as `planner_revision`)
- `turn_id` generation
- `action_id` generation

Changing the revision intentionally invalidates all derived IDs.

## 4. Candidate generation

Candidates are derived from structured context evidence.  Each candidate
must be supported by at least one evidence source.

### 4.1 Candidate categories

| Category | Evidence sources |
| --- | --- |
| Advance goal | chapter goal, active plot threads |
| Investigate unknown | unresolved plot threads, world locations with unknown state |
| Mitigate risk | current conflicts, world rule constraints |
| Protect resource | available resources, character status |
| Negotiate / relation | relationships, character dispositions |
| Retreat / wait | time window constraints, location safety |
| High-cost breakthrough | resources that could be spent, capability trade-offs |
| Sacrifice for progress | resource inventory, relationship capital |

### 4.2 Evidence types

- Chapter goal (from `story_planning.json` chapters[i].goal)
- Active conflicts (from `story_planning.json` chapters[i].conflicts)
- Plot threads (from `story_planning.json` chapters[i].plot_threads)
- Planning dependencies (from `data/planning_control/dependencies.json`)
- Character capabilities (from `data/characters.json`)
- Available resources (from `data/world_bible.json` resources)
- Locations (from `data/world_bible.json` locations)
- World rules (from `data/world_bible.json` core_rules / taboos)
- Relationships (from `data/characters.json` relationship fields)
- Branch-local projected state (from `data/narrative_memory/state/{timeline_id}/{branch_id}/current.json` — branch-scoped only; the legacy flat `data/narrative_memory/state/current.json` is NOT read)

## 5. Scoring rules

Each candidate receives an integer score from the sum of:

| Component | Weight | Source |
| --- | --- | --- |
| Goal relevance | +30 | Chapter goal keyword match |
| Urgency | +20 | Active conflict / unresolved thread |
| Evidence support | +10 per evidence type | Number of distinct evidence sources |
| Conflict differentiation | +15 | Addresses a different conflict than other candidates |
| Capability compatibility | +10 | Character has relevant capability |
| Unavailable penalty | -50 | Missing required capability/resource/location |
| Semantic duplication | -30 | Same intent as higher-ranked candidate |

The scoring function is fully deterministic: same inputs → same scores.

## 6. Exactly-3 selection

Final `recommended_actions` always contains exactly 3 items with
`deterministic_order` 1, 2, 3.

### 6.1 Diversity constraints

- All 3 `action_id` values must be unique.
- All 3 `intent` values must be unique (normalized).
- Action types should not all be identical (at least 2 different types).
- Semantic categories must differ (checked via category tag).

### 6.2 Insufficient evidence policy

If there are fewer than 3 viable candidates:
1. Fill remaining slots with conservative "wait / observe" candidates.
2. Mark them with `unavailable_reasons` containing `CONTEXT_INSUFFICIENT`.
3. Do NOT fabricate evidence (no invented characters, resources, or locations).

## 7. Action ID generation

```
action_id = sha256(
    planner_revision + ":" +
    context_fingerprint + ":" +
    normalized_intent + ":" +
    action_type + ":" +
    str(deterministic_order)
)[:16]
```

Stable inputs → stable ID.  Display text, punctuation, and clock time
do NOT participate.

## 8. Turn ID generation

```
turn_id = sha256(
    planner_revision + ":" +
    context_fingerprint + ":" +
    parent_turn_id  # may be empty string for root
)[:16]
```

## 9. Determinism guarantees

| Property | Guaranteed |
| --- | --- |
| Same context → same plan fingerprint | Yes |
| Same context → same turn_id | Yes |
| Same context → same action_ids | Yes |
| Same context → same recommendation order | Yes |
| Clock injection changes IDs | No |
| Display text changes IDs | No |

## 10. Limitations

- **No LLM / NLU**: Candidates come from keyword matching and structured
  data only.  There is no semantic understanding beyond exact and
  substring matching against known names.
- **Conservative**: When evidence is ambiguous or missing, the planner
  prefers `requires_clarification` and `unavailable` over speculative
  action suggestions.
- **Qualitative only**: Scores are ordinal (for ordering), not calibrated
  probabilities.
- **v1 scope**: Candidate generation covers the most common narrative
  action patterns; exotic or highly domain-specific actions may not be
  represented.

## 11. Test coverage

See [test_phase0d4b_narrative_turn_planner.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4b_narrative_turn_planner.py):

- 124 focused tests (85 original + 26 FIX-RC + 13 FIX-RC-FV: cold-start read-only, deep immutability, strict canonical serialization, branch state isolation, complete fingerprint, branch-state path lock, custom action length lock, missing-vs-invalid lock, test-count lock)
- Exactly-3 actions verification
- Stable turn_id / action_id
- Semantic diversity checks
- Insufficient context handling
- Planner revision ID invalidation
- Clock injection independence
