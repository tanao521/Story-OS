# Next Chapter Risk Matrix

## Cold-start classification (fixture-verified 2026-07-28)

| Operation | Classification | Fixture evidence | Severity |
|---|---|---|---|
| `SimulatorLoopStateService.build()` | PURE_READ (with KeyError bug) | 0 file delta; KeyError: 'revision' on all fixtures | P1 |
| `NarrativeTurnContextBinder.bind()` | PURE_READ | Direct file reads; class contract forbids initialization | Safe |
| `list_versions()` | PURE_READ | 0 file delta across Fixtures A/B/C | Safe |
| `get_selected_version()` | **HIDDEN_MUTATION_BEHIND_READ** | +1 file (`chapter_NNN_versions.json`) on all fixtures | **P1** |
| `RevisionService.read_active_canon()` | PURE_READ | 0 file delta across all fixtures | Safe |
| `RevisionService.active_canon()` | **LEGACY_READ_WITH_SIDE_EFFECT** | +3 files (Canon+index+audit) on Fixture A; error on absent chapter | **P0** |
| `planning_service.load_planning()` | PURE_READ with nondeterministic normalization | 0 file delta; in-memory ID/timestamp fill | Safe |
| `BranchMemoryService.retrieval_history(selected=None)` | PURE_READ | Returns stored entries | Safe |
| `BranchMemoryService.retrieval_history(selected=...)` | EXPLICIT_INITIALIZATION/mutation | Appends retrieval history | P1 |

**Policy**: `get_selected_version()` and `active_canon()` are FORBIDDEN for
next-chapter resolve/browse paths. Both create production mutations as side
effects of reads.

## Gap matrix

| Gap | Severity | Current behavior (fixture-verified) | Required behavior | Authority impact | Proposed phase |
|---|---|---|---|---|---|
| Next chapter resolution | **P1** | File existence + numeric `N+1` only; `SimulatorLoopStateService.build()` has KeyError bug | Pure registry-backed resolution with robust manifest parsing | Shared read adapter | 0D6-A after decision |
| Chapter creation | **P0** | No unified operation; writers create partial artifacts (`get_selected_version` creates index, `active_canon` creates Canon) | Exactly-once lifecycle operation | New durable authority | Design gate |
| Current chapter selection | **P1** | State and planning-derived pointers differ (`state.current_chapter` vs `next_chapter_plan.chapter_id`) | Separate committed/opened pointers | Migration/adapter | Design gate |
| Initial source version | **P1** | Empty chapter allowed; `get_selected_version()` read writes index | Explicit source initialization | Existing writer wiring | 0D6-A after decision |
| Initial Canon | **P0** | `active_canon()` compatibility read auto-creates Canon | Explicit policy and mutation | Canon authority | Design gate |
| Branch carry-forward | **P1** | Registry is cross-chapter; no chapter transition contract in `branch_narrative_memory_service.py` | Explicit reuse and CAS | Existing branch authority | 0D6-B |
| Memory carry-forward | **P1** | Branch events and state exist (verified in `branch_narrative_memory_service.py`); selection contract absent | Typed read composition | Read adapter | 0D6-B |
| Vector readiness | **P1** | Branch/Canon manifest gate exists (verified in `vector_index_lifecycle.py`); `SimulatorLoopStateService.build()` has manifest KeyError | Target-chapter readiness result | Existing vector authority + bug fix | 0D6-B |
| Planning cursor | **P1** | `current_chapter+1` and next plan compete (`planning_service.py`, `web/routes.py`) | Explicit projection | Planning/state contract | Design gate |
| Completion warnings | **P1** | One aggregate warning status (`committed_with_warnings`) | Typed blocking classes | Commit read adapter | 0D6-B |
| Traditional sharing | **P1** | Same files, different target resolution (`current_target_chapter()` vs Completion file check) | Shared chapter resolver | Shared adapter | 0D6-A |
| URL navigation | **P2** | Clears artifact IDs but uses numeric target (`nextChapter()` pushes `chapter_id=N+1`) | Authority-issued target | UI only after backend | 0D6-C |
| Recovery | **P0** | No Chapter-create operation result exists | Exactly-once result/phase | New authority if approved | 0D6-A |
| Scope isolation | **P0** | Existing artifacts are scoped, chapter resolver is not registry-backed | Full-scope resolver/CAS | Read and mutation guards | 0D6-RC |

## Concurrency and recovery matrix

| Scenario | Expected winner | Required CAS/fingerprint | Recovery source | Fail-closed behavior | Forbidden duplicate |
|---|---|---|---|---|---|
| create vs create | First durable claim | operation request fingerprint + chapter-set CAS | create result | chapter identity | second initialization |
| create vs chapter appears | existing/first committed authority | chapter-set CAS | resolver plus result | second initialization |
| create vs Branch archive | registry CAS winner | expected branch revision | branch journal/create result | state in archived branch |
| create vs active Branch switch | explicit policy winner | expected active Branch | registry journal | wrong-branch carry-forward |
| create vs Planning update | first valid fingerprint | expected Planning fingerprint | create result | mixed plan |
| create vs Canon revision change | first valid predecessor fingerprint | expected Canon/Commit fingerprint | Commit and create result | stale carry-forward |
| create vs selected version change | create contract winner | expected source index fingerprint | version/create result | hidden reselection |
| response loss after creation | completed operation | no new operation ID | durable create result | second chapter |
| durable result exists but phase missing | result wins if fingerprint valid | repair phase projection only | durable result | repeated writes |
| refresh during creation | operation unchanged | GET only | durable phase/result | new mutation |
| Back/Forward during creation | operation unchanged | URL is non-authoritative | durable phase/result | URL-triggered create |
| Traditional creates while Simulator resolves | TBD by owner decision | shared chapter CAS | shared resolver | conflict error |
| create vs Vector manifest update | create must verify manifest | expected vector manifest fingerprint | vector manifest + create result | stale vector carry-forward |