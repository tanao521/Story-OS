# Cross-Chapter Continuity Contract

## Existing-next-chapter flow

1. Read the terminal Chapter N Commit result.
2. Resolve Chapter N+1 through a pure Chapter authority adapter.
3. Navigate only after an explicit user action.
4. Clear Candidate, Review, Commit, Turn and action URL identities.
5. Bind Chapter N+1 source and its same-chapter Canon policy.
6. Reuse the active timeline-global Branch identity.
7. Read the selected Branch State and prior chapter Branch Memory.
8. Start no Turn mutation until all readiness gates pass.

## Missing-next-chapter flow

The present product must show an unavailable/setup state. The current
Traditional workflow has planning and draft generation mutations, but no
single exactly-once Chapter lifecycle operation suitable for Simulator reuse.
Frontend directory creation or frontend `N+1` authority is forbidden.

**Fixture evidence (2026-07-28):**
- `get_selected_version()` on missing chapter → **creates versions index** (HIDDEN_MUTATION_BEHIND_READ)
- `active_canon()` on missing chapter file → **creates Canon** (LEGACY_READ_WITH_SIDE_EFFECT)
- Both paths are FORBIDDEN for next-chapter resolution/browsing
- `list_versions()` and `read_active_canon()` are safe pure reads

## Carry-forward source order

1. Chapter N terminal Commit result and committed Canon identify the completed
   predecessor.
2. Branch-scoped projected Narrative State supplies current branch facts.
3. Branch-scoped confirmed memory events and chapter snapshots supply durable
   history.
4. Chapter N summary and legacy memory index provide project-level background.
5. Chapter N+1 Planning record supplies target intent.
6. Chapter N+1 selected source and same-chapter Canon policy bind the new Turn.
7. Vector retrieval is advisory and must use project/timeline/branch/Canon
   filters; stale vectors never override deterministic authorities.

## Invariants

- Chapter N Commit always uses `ChapterCommitService`.
- Creating N+1 never changes N Candidate, Review, Commit, Canon, History, or
  selected version.
- N+1 never inherits N operation IDs or Candidate URL parameters.
- History remains immutable and queries filter record `chapter_id`.
- A Candidate must match project, timeline, branch, chapter and source.
- Branch A data never enters Branch B context.
- Branch browsing changes neither active Branch nor Chapter authority.
- Refresh, Back and Forward create no Chapter.
- Resolution and browsing are pure reads (except confirmed mutation paths
  `get_selected_version()` and `active_canon()` which are FORBIDDEN).
- The frontend generates no Chapter identity.
- A Chapter create request binds predecessor Commit fingerprint, expected
  chapter-set fingerprint, Planning fingerprint, active Branch registry
  revision, and Canon policy.
- Same operation/same request replays; same operation/different request
  conflicts; concurrent creates have one winner.

## Completion page invariants

- "Start next chapter" button (`[data-start-next-chapter]`) is disabled when
  `chapter_progression.next_chapter_available` is false.
- Button click performs pure URL navigation via `SimulatorCandidateReview.nextChapter()`.
- No backend API call is made for next-chapter navigation.
- No chapter creation is triggered by the Completion view.
- The Completion view only checks for existing chapter file existence.

## Artifact keys

| Artifact | Required keys |
|---|---|
| Turn Plan | project, timeline, branch, chapter, source, turn, context fingerprint |
| Turn Result | full scope, turn, operation, source fingerprint |
| Transition | full branch scope, turn, sequence, previous fingerprint |
| History | branch path plus record chapter |
| Candidate | full scope, candidate, source/Canon/registry fingerprints, included Turns |
| Review | candidate, operation, reviewer decision, candidate fingerprint |
| Commit | full scope, candidate, operation, ordered Turns, durable result |

## Cold-start read classification (fixture-verified)

| Read path | Classification | Evidence |
|---|---|---|
| `SimulatorLoopStateService.build()` | PURE_READ (with bug) | 0 file delta; KeyError on manifest format |
| `NarrativeTurnContextBinder.bind()` | PURE_READ | Direct file reads |
| `list_versions()` | PURE_READ | 0 file delta across all fixtures |
| `get_selected_version()` | **HIDDEN_MUTATION_BEHIND_READ** | +1 file (versions index) on all fixtures |
| `read_active_canon()` | PURE_READ | 0 file delta across all fixtures |
| `active_canon()` | **LEGACY_READ_WITH_SIDE_EFFECT** | +3 files (Canon+index+audit) on Fixture A |
| `load_planning()` | PURE_READ | 0 file delta; in-memory normalization only |
| `BranchMemoryService.retrieval_history(selected=None)` | PURE_READ | Returns stored entries |
| `BranchMemoryService.retrieval_history(selected=...)` | EXPLICIT_MUTATION | Appends retrieval history |

**Policy**: All HIDDEN_MUTATION and LEGACY_READ_WITH_SIDE_EFFECT paths are
**FORBIDDEN** for next-chapter resolve/browse. Only PURE_READ paths may be used.