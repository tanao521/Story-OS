# Simulator Action Feasibility Engine — Design Document

> Phase 0D4-B implementation.  Pure computation — no Provider, no writes.

## 1. Purpose

The `NarrativeActionFeasibility` engine validates narrative actions
(recommended or custom) against deterministic evidence from the context
snapshot.  It produces one of four statuses with structured reason codes.

## 2. Module location

File: [narrative_action_feasibility.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_action_feasibility.py)

## 3. Validation status hierarchy

Strict priority order (highest wins):

```
blocked
> requires_clarification
> allowed_with_cost
> allowed
```

A single `blocked` reason overrides all other positive findings.
A single `requires_clarification` overrides `allowed_with_cost` and
`allowed`.

### 3.1 Status definitions

| Status | Meaning |
| --- | --- |
| `blocked` | Deterministic evidence proves the action cannot be executed. |
| `requires_clarification` | Information is insufficient to determine feasibility. |
| `allowed_with_cost` | Action is feasible but has known deterministic costs. |
| `allowed` | All necessary conditions met; no significant known costs. |

## 4. Pipeline order (14 steps)

Steps execute in fixed order.  If any step produces a `blocked` result,
the pipeline short-circuits and returns immediately.

| Step | Check | Status on failure |
| --- | --- | --- |
| 1 | Input validation (empty, length, control chars) | `blocked` |
| 2 | Context / scope binding (project, timeline, chapter) | `blocked` |
| 3 | Source and revision freshness | `blocked` if stale |
| 4 | Branch status (active, not archived) | `blocked` |
| 5 | Action structure extraction (verb, target, object, location) | `requires_clarification` |
| 6 | World-rule check (taboos, core rules) | `blocked` on conflict |
| 7 | Canon conflict check (established facts) | `blocked` on direct conflict |
| 8 | Character capability check | `blocked` / `requires_clarification` |
| 9 | Resource check (availability) | `blocked` / `allowed_with_cost` |
| 10 | Location check (reachability / presence) | `blocked` / `requires_clarification` |
| 11 | Time-window check (narrative timing constraints) | `blocked` |
| 12 | Relationship / permission check | `blocked` / `allowed_with_cost` |
| 13 | Dependency check (blocking planning dependencies) | `blocked` |
| 14 | Cost / risk classification | `allowed_with_cost` |

## 5. Reason codes

### 5.1 Input-level

| Code | Meaning |
| --- | --- |
| `ACTION_EMPTY` | Action text is empty or whitespace-only. |
| `ACTION_TOO_LONG` | Action text exceeds maximum length. |
| `ACTION_UNPARSEABLE` | Action structure cannot be extracted. |
| `ACTION_TARGET_AMBIGUOUS` | Action target matches multiple entities. |
| `ACTION_OBJECT_AMBIGUOUS` | Action object matches multiple entities. |

### 5.2 Context-level

| Code | Meaning |
| --- | --- |
| `CONTEXT_STALE` | Context fingerprint does not match current state. |
| `SOURCE_STALE` | Source version has changed since context binding. |
| `CONTEXT_INSUFFICIENT` | Not enough evidence to assess feasibility. |

### 5.3 Branch-level

| Code | Meaning |
| --- | --- |
| `BRANCH_NOT_ACTIVE` | Branch is not the currently active branch. |
| `BRANCH_ARCHIVED` | Branch has been archived. |

### 5.4 World / Canon

| Code | Meaning |
| --- | --- |
| `WORLD_RULE_CONFLICT` | Action violates a world rule or taboo. |
| `CANON_CONFLICT` | Action directly contradicts established canon. |

### 5.5 Capability / Resource / Location / Time

| Code | Meaning |
| --- | --- |
| `CAPABILITY_MISSING` | Required character capability is absent. |
| `RESOURCE_MISSING` | Required resource does not exist. |
| `RESOURCE_COST_HIGH` | Resource exists but cost is significant. |
| `LOCATION_MISMATCH` | Action requires a different location. |
| `TIME_WINDOW_CLOSED` | Narrative time window for this action has passed. |

### 5.6 Relationship / Dependency

| Code | Meaning |
| --- | --- |
| `RELATIONSHIP_PERMISSION_MISSING` | Action requires a relationship or permission not present. |
| `DEPENDENCY_BLOCKED` | A planning dependency must be resolved first. |

## 6. Custom action normalization

`normalize_custom_action(text)` performs:

1. Unicode NFKC normalization
2. Strip leading/trailing whitespace
3. Collapse internal whitespace to single spaces
4. Reject NUL and control characters (except common whitespace)
5. Length check against `MAX_CUSTOM_ACTION_LENGTH` (200 chars)
6. Empty check

### 6.1 Security properties

- Does NOT execute code
- Does NOT parse HTML
- Does NOT read file paths
- Does NOT invoke shell
- Does NOT call Provider
- Does NOT interpret "ignore previous instructions" as an attack

### 6.2 Persistence boundary

Only the SHA-256 hash of the normalized text is stored in persistent
objects.  The full text is ephemeral within the function call.

## 7. Deterministic natural language scope

The feasibility engine uses **only** deterministic extraction:

- Exact keyword matching for verbs (known action dictionary)
- Exact and substring matching for character names
- Exact and substring matching for location names
- Exact and substring matching for resource names
- Simple pattern matching for action frames (verb-target-object)

What it does NOT do:
- General natural language understanding
- Semantic inference
- Coreference resolution
- Implicature or pragmatics
- LLM-based interpretation

When extraction cannot determine a required field unambiguously,
`requires_clarification` is returned.

## 8. Validation fingerprint

```
validation_fingerprint = sha256(
    context_fingerprint + ":" +
    action_id + ":" +
    validation_status + ":" +
    sorted(reason_codes) + ":" +
    feasibility_revision
)
```

Same inputs → same fingerprint.

## 9. Multi-language support

Both Chinese and English input are handled identically:
- No crash on non-Latin characters
- Same input → same normalized result
- Unknown verbs / entities → `requires_clarification`
- No fabricated evidence for unrecognized input

## 10. Test coverage

124 focused tests (85 original + 26 FIX-RC + 13 FIX-RC-FV) in [test_phase0d4b_narrative_turn_planner.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4b_narrative_turn_planner.py), including:

- Input validation (empty, whitespace, over-length, control chars)
- Unicode normalization
- Ambiguous target / object
- World rule / canon conflict
- Capability / resource / location / time checks
- All 4 status classifications
- Custom action hash stability
- Stale context rejection
