# Chapter Progression Authority Map

## Repository facts

- Runtime chapter identity is a positive integer rendered into
  `data/chapters/chapter_NNN.md`, version filenames, summary filenames, and
  Canon directories. See `ProjectContext.chapters_dir`,
  `version_manager.format_chapter_id()`, and `revision_service._chapter_path()`.
- `data/chapter_index.json` is created by `core.project.ensure_project_structure()`
  but no production chapter navigation or Simulator read path consumes it.
- `web.routes.api_simulator_context()` discovers chapters by scanning chapter
  and version filenames and adding `state.current_chapter`.
- Planning permits an opaque `chapter_id` plus a numeric `chapter_number`;
  `NarrativeTurnContextBinder._find_chapter_plan()` accepts either.
- `web.routes.current_target_chapter()` resolves `next_chapter_plan.chapter_id`
  first, otherwise returns `state.current_chapter + 1`.

## Fixture probe evidence (2026-07-28)

SHA-256 probe results from temporary isolated fixtures:

| Probe | Fixture A (exists) | Fixture B (absent) | Fixture C (branch) | Classification |
|---|---|---|---|---|
| `list_versions(2)` | 0 delta | 0 delta | 0 delta | PURE_READ |
| `get_selected_version(2)` | **+1 file** (versions index) | **+1 file** (versions index) | **+1 file** (versions index) | **HIDDEN_MUTATION_BEHIND_READ** |
| `read_active_canon(2)` | 0 delta | 0 delta | 0 delta | PURE_READ |
| `active_canon(2)` | **+3 files** (Canon+index+audit) | Error (no chapter file) | Error (no chapter file) | **LEGACY_READ_WITH_SIDE_EFFECT** |
| `SimulatorLoopStateService.build()` | KeyError: 'revision' | KeyError: 'revision' | KeyError: 'revision' | PURE_READ (implementation bug) |
| `load_planning()` | 0 delta | 0 delta | 0 delta | PURE_READ |

Key findings:
1. **`get_selected_version()` creates `chapter_NNN_versions.json`** — a compatibility read that mutates empty chapters.
2. **`active_canon()` creates Canon content, index and audit** — legacy initialization behind a read, blocked when chapter file is absent.
3. **`SimulatorLoopStateService.build()` crashes** on branch manifest format (`KeyError: 'revision'`) when manifests lack the expected structure.

## Authority matrix

| Concern | Existing authority | Scope | Mutation owner | Recovery | 0D6 decision |
|---|---|---|---|---|---|
| Chapter identity | Integer chapter number encoded in paths; Planning has a second plan identity | Project/chapter | Multiple legacy writers | Filesystem rescan | **BLOCKED_BY_UNCLEAR_SEMANTICS** |
| Chapter creation | No standalone chapter lifecycle operation; draft/version and Commit writers create artifacts | Project/chapter | `VersionWriterFacade`, commands, `ChapterCommitService` | Writer operation records vary | **REQUIRES_NEW_DURABLE_AUTHORITY** |
| Current chapter | `data/state.json.current_chapter`; Traditional target may derive `+1` | Project | `ChapterCommitService`, legacy commands | State file | **BLOCKED_BY_UNCLEAR_SEMANTICS** |
| Source version | Version index plus chapter-local draft/edited/manual files; `get_selected_version()` writes index on read | Chapter | `VersionWriterFacade`, `select_version()`, `load_versions_index()` | Version operation authority | **REQUIRES_EXISTING_MUTATION_WIRING** (must not use compatibility read) |
| Active Canon | `data/canon_versions/chapter_NNN/index.json`; `active_canon()` initializes on read | Chapter | `RevisionService` / `ChapterCommitService` | Canon index and commit run | **REQUIRES_EXISTING_MUTATION_WIRING** (must not use `active_canon()`) |
| Branch continuity | Registry under `data/branches/{timeline}`; branch identity is timeline-global | Project/timeline | `NarrativeBranchStore` | Immutable registry journal | **REUSE_AS_IS** |
| Branch state | `narrative_memory/state/{timeline}/{branch}/current.json` with mutable chapter field | Timeline/branch, with mutable chapter field | Narrative Turn projection | Result/transition journals | **REQUIRES_EXISTING_MUTATION_WIRING** |
| Turn history | Immutable Turn records under timeline/branch; records include chapter | Timeline/branch/chapter record | `NarrativeTurnService` | Turn operation authority | **REUSE_WITH_READ_ADAPTER** |
| Candidate | Candidate Version with embedded full scope | Project/timeline/branch/chapter/source | `NarrativeChapterCompiler` | Compile operation | **REUSE_AS_IS** |
| Review | First-writer-wins Candidate decision | Candidate/full scope | `NarrativeCandidateReviewService` | Review operation | **REUSE_AS_IS** |
| Commit completion | Commit operation result plus `ChapterCommitService` run | Chapter/candidate/full scope | Existing commit route and service | Durable result/read model | **REUSE_AS_IS** |
| Memory carry-forward | Branch events by chapter plus branch-global projected state; legacy memory index | Timeline/branch/chapter | Existing memory and Turn services | Journals/snapshots | **REQUIRES_EXISTING_MUTATION_WIRING** |
| Vector readiness | Branch manifest bound to Canon revision; manifest must match branch lifecycle | Project/timeline/branch/Canon | Vector lifecycle | Operation phase and manifest | **REQUIRES_EXISTING_MUTATION_WIRING** |
| Traditional selected version | Chapter-local versions index | Chapter | `select_version()` | Version index | **REUSE_WITH_READ_ADAPTER** |
| Completion next-chapter | File existence check via `chapter_progression.next_chapter_available`; pure frontend URL navigation | Chapter | No backend mutation | None | **EXISTING_NEXT_CHAPTER_NAVIGATION** |

## Required owner decisions

1. Declare whether numeric chapter number is the sole lifecycle identity and
   whether Planning `chapter_id` is only a plan-record identity.
2. Select one shared explicit Chapter create-or-resolve mutation owner.
3. Define whether `state.current_chapter` means last committed chapter or
   currently opened chapter. It cannot safely represent both.
4. Define initial Chapter N+1 Canon semantics. The current Turn binder requires
   same-chapter Canon and does not carry Chapter N Canon as Chapter N+1 Canon.
5. Define the cross-chapter Branch State transition and its CAS inputs.
6. Prohibit `get_selected_version()` and `active_canon()` in next-chapter
   resolve/browse paths due to confirmed cold-start mutation side effects.
7. Fix `SimulatorLoopStateService.build()` branch manifest `KeyError: 'revision'`
   before relying on it for cross-chapter readiness projection.