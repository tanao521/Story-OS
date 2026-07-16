# Story OS 16.4-A deletion audit and final regression preparation

**Status:** read-only audit completed on 2026-07-16. This document is a decision record, not deletion authority. No source, test, frontend, data, temporary directory, backup, route, or module was deleted, moved, or renamed.

## 1. Scope, baseline, and audit method

* Repository root: `D:\novel\StoryOS`; project root: `D:\novel\StoryOS\story-os-demo`.
* Branch: `agent/phase-13-2-memory-repair`.
* No commit, push, pull request, test run, compilation, application start, HTTP smoke, browser run, model call, or cleanup was performed by this stage.
* The only permitted stage outputs are this document and the short 16.4-A summary appended to the engine merge map.

### Protected-data baseline

| File | SHA-256 at audit start |
| --- | --- |
| `data/story_blueprint.json` | `FF4228FE0C6D88461858F52E388F295C012135D33D17EB1E1970E1A56113FD9B` |
| `data/next_chapter_plan.json` | `61293F312CE2FF901B7A584B5259FC01B251D500644DF97466D4E3DF1F5BD62E` |
| `data/state.json` | `9974FDB407ABABF84DED5557CDD226E3A8D3FD49A95E9DFA8768A6173532E031` |

### Evidence sources used

The audit used static, read-only inspection of Python imports/calls, FastAPI decorators and `web/app.py` router inclusion, CLI dispatch in `main.py`, `commands.py` call sites, template script tags and DOM handlers, JavaScript request/event references, `web/api_registry.py`, API and frontend contract tests, storage-path readers/writers, Git tracked/untracked listings, and file metadata.

Dynamic-risk checks were also made for `importlib`, `__import__`, `getattr`, `include_router`, JobManager dispatch, and CLI string dispatch. Dynamic imports exist in unrelated production paths (for example evaluation production and self-check), so absence from a simple text search is never used as sole deletion evidence. Where evidence is incomplete, the classification is `DEFER_INVESTIGATE`.

## 2. Classification summary

Counts below are decision-record objects, not a claim that the repository has only this many symbols.

| Classification | Count | Decision |
| --- | ---: | --- |
| `KEEP_ACTIVE` | 6 | Canonical services or shared safety/transport components. |
| `KEEP_ANALYZER` | 2 | Quality and continuity evidence producers. |
| `KEEP_COMPAT` | 11 | Compatibility routes and symbol-level bridges. |
| `KEEP_DATA_READER` | 2 | Legacy quality/continuity projections. |
| `KEEP_TEST_INFRA` | 3 | Compatibility, data-protection, and frontend isolation contracts. |
| `DELETE_CANDIDATE` | 0 | No code or frontend object meets every required deletion condition. |
| `TEMP_CLEANUP_CANDIDATE` | 14 | Isolated pytest basetemp directories; approval still required. |
| `DEFER_INVESTIGATE` | 1 | Unmounted planning studio script with test/document references. |
| `DATA_RETENTION_DEFER` | 9 | Six real-data backups plus Canon/Memory/Vector history groups. |

## 3. Symbol and route decision matrix

| ID | Object | Type | Current responsibility | Runtime / dynamic evidence | Frontend, compatibility, data, and test evidence | Replacement | Risk | Classification | Preconditions before deletion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `PlanningMutationService` | service | Whitelisted planning write entry | Called by planning routes and legacy planning write paths | Planning mutation API/service tests; writes remain authoritative | None; it is the authority | R4 | KEEP_ACTIVE | Not a deletion subject. |
| A2 | `DataStoreWriteFacade` | write facade | Shared guarded atomic write boundary | Called by planning and version facades | Write-facade tests and protected-data constraints | None; it is the authority | R4 | KEEP_ACTIVE | Not a deletion subject. |
| A3 | `EvaluationService` | service | Canonical EvaluationReport lifecycle | Registered in canonical evaluation routes | Evaluation API/contract tests; evaluation storage ownership | None; it is the authority | R4 | KEEP_ACTIVE | Not a deletion subject. |
| A4 | `RevisionService` | service | Revision request/candidate/canon workflow | Registered by `/api/revisions*` handlers | Revision API/service tests and canon/archive responsibility | None; it is the authority | R4 | KEEP_ACTIVE | Not a deletion subject. |
| A5 | `VersionWriterFacade` | service | Work-version and selected-index write boundary | Called by commands and `version_manager` compatibility functions | Version writer and compatibility tests | None; it is the authority write boundary | R4 | KEEP_ACTIVE | Not a deletion subject. |
| A6 | `ContextAssemblyService` | service | Read-only ContextPackage assembly | Called by CLI, context bridge, and context-preview route | Context assembly tests; reads state/memory/spec assets without write | None; it is the authority | R4 | KEEP_ACTIVE | Not a deletion subject. |
| E1 | `system/quality_checker.py::build_quality_report` and `save_quality_report` | analyzer | Produces legacy quality evidence | Reached by `commands.quality_check_command`; CLI `quality-check` remains registered | `/api/quality-check`, legacy quality reader, route/quality tests | Future evidence producer migration only; no current replacement | R4 | KEEP_ANALYZER | Prove all producers and legacy evidence consumers are retired. |
| E2 | `system/continuity_checker.py::check_chapter_continuity` and `save_continuity_report` | analyzer | Produces continuity evidence | Called by `/api/continuity-check` and revision candidate checks | `/api/continuity-report`, legacy reader, route tests | Future evidence producer migration only; no current replacement | R4 | KEEP_ANALYZER | Prove all producers and legacy evidence consumers are retired. |
| D1 | `LegacyEvaluationAdapter.quality_view` | reader | Projects historical quality reports as read-only legacy view | Called by `/api/quality-report` | Compatibility registry and adapter/API tests; old report schema responsibility | Canonical Evaluation views do not parse every legacy report shape | R3 | KEEP_DATA_READER | Migrate/read-verify historical reports and clear compatibility contract. |
| D2 | `LegacyEvaluationAdapter.continuity_view` | reader | Projects historical continuity reports as read-only legacy view | Called by `/api/continuity-report` | Compatibility registry and adapter/API tests; validates old content hashes | Canonical Evaluation views do not replace it | R3 | KEEP_DATA_READER | Migrate/read-verify historical reports and clear compatibility contract. |
| C1 | `/api/quality-report` | compatibility GET route | Legacy quality response shape and headers | Explicit decorator and registry entry | `app.js`, API contract, adapter, and report API tests | `/api/evaluations` for new work | R3 | KEEP_COMPAT | External contract inventory is empty and legacy reader is retired. |
| C2 | `/api/continuity-report` | compatibility GET route | Legacy continuity response shape and headers | Explicit decorator and registry entry | API/adapter/route tests | `/api/evaluations` for new work | R3 | KEEP_COMPAT | External contract inventory is empty and legacy reader is retired. |
| C3 | `/api/planning/next-chapter` | compatibility GET/POST route | Legacy plan payload; writes delegate to planning authority | Explicit decorators and registry entry | `app.js` and planning mutation API tests | `/api/planning/overview` plus PlanningMutationService | R3 | KEEP_COMPAT | Verify no frontend, CLI, test, or external caller needs legacy payload. |
| C4 | `/api/quality-check` | deprecated internal producer | Creates quality evidence through command adapter | Explicit decorator; CLI `quality-check` still registered | Hidden primary UI function, route contracts, old report production | No proven replacement producer | R4 | KEEP_COMPAT | First retire analyzer responsibility; then clear CLI/API/test contracts. |
| C5 | `/api/continuity-check` | deprecated internal producer | Creates continuity evidence | Explicit decorator; revision flow uses checker | Hidden primary UI function, route tests, old report production | No proven replacement producer | R4 | KEEP_COMPAT | First retire analyzer responsibility; then clear API/test contracts. |
| C6 | `context_builder.build_working_context` | compatibility symbol | Preserves old context payload while delegating to assembly service | Called in author/archive/context-builder tests | Legacy return fields and tests remain public behavior | `ContextAssemblyService` underneath | R3 | KEEP_COMPAT | Enumerate external/CLI consumers and migrate compatibility payload contracts. |
| C7 | `version_manager.format_chapter_id` | compatibility symbol | Legacy version file naming | Called by version manager functions | Historical path/filename schema responsibility | None | R4 | KEEP_COMPAT | Historical-version migration and naming compatibility decision. |
| C8 | `version_manager.list_versions` | compatibility symbol | Scans and lists historical work versions | Called by commands, routes, writer facade | Version API/manager tests and historical data reading | No complete replacement reader | R4 | KEEP_COMPAT | Replace reader and prove historical project coverage. |
| C9 | `version_manager.load_versions_index` | compatibility symbol | Reads/rebuilds legacy selected index | Called by commands and selection functions | selected pointer compatibility tests | `VersionWriterFacade` writes only; it does not replace reads | R4 | KEEP_COMPAT | Replace historical index reader and verify all schemas. |
| C10 | `version_manager.select_version` / `get_selected_version` | compatibility symbols | Selected-pointer compatibility behavior | Called by commands and version flows | Version-manager compatibility tests | Writer facade performs writes, not API semantic replacement | R4 | KEEP_COMPAT | Replace public selection/read contract and test migration. |
| C11 | `version_manager.save_versions_index` | compatibility symbol | Delegates legacy index persistence to facade | Called by load/select/archive/commands | Monkeypatch compatibility and writer-facade tests | `VersionWriterFacade.write_versions_index` | R3 | KEEP_COMPAT | Remove only after callers directly use facade and legacy index shape is retired. |
| F1 | `#narrative-evaluation-center` and `narrative-evaluation.js` | primary frontend | Sole visible evaluation navigation and report workflow | Template script tag and `DOMContentLoaded` initialization | Frontend evaluation contracts | None; primary entry | R2 | KEEP_ACTIVE | Not a deletion subject. |
| F2 | `qualityCheck`, `qualityCheckCurrentVersion`, `checkContinuity` and their hidden buttons | hidden frontend compatibility | Retains old version/quick-action behavior while suppressing duplicate entry | `app.js` functions and template `onclick`; runtime hide selectors | Frontend consolidation test asserts functions remain; routes still valid | Narrative evaluation center for primary flow | R2/R3 | KEEP_COMPAT | Remove only after deep-link/event/API compatibility and tests are retired. |
| F3 | `web/static/planning-studio.js` | unmounted frontend file | Old/experimental planning UI request helper | No script tag found in current template | Referenced by `test_frontend_request_isolation.py` and planning audit document; route mismatch history is documented | No runtime replacement decision recorded | R1/R2 | DEFER_INVESTIGATE | Verify no dynamic script loader, deep link, external embed, or planned recovery responsibility; then review its test contract. |
| T1 | `tests/test_api_compatibility_routes.py` and `tests/test_evaluation_legacy_adapter.py` | test infrastructure | Locks route registry, headers, and legacy reader behavior | Not production runtime; explicit contract imports | Guards C1-C5 and D1-D2 | None while compatibility remains | R3 | KEEP_TEST_INFRA | Candidate only after associated route/reader approval and replacement coverage. |
| T2 | `tests/test_real_data_protection.py` | test infrastructure | Protects real project data boundary | Static/fixture protection role | Required before and after any deletion batch | None | R4 | KEEP_TEST_INFRA | Not a deletion subject. |
| T3 | `tests/test_frontend_entry_consolidation.py` and `tests/test_frontend_request_isolation.py` | test infrastructure | Locks single entry and project-isolated requests | Reads templates/scripts, including F3 | Prevents regressions in visible/hidden entry boundary | None | R2 | KEEP_TEST_INFRA | Review only with a separately approved frontend removal batch. |

There are **no `DELETE_CANDIDATE` rows**. In particular, hidden controls, deprecated routes, an unmounted script, and a legacy write wrapper each fail at least one required condition (compatibility, producer, test, historical-schema, or dynamic-reference certainty).

## 4. Route audit

`web/app.py` includes the primary router plus analytics, author, creative-loop, and planning-control routers. Static decorator inspection found the expected broad route surface; this stage did not attempt bulk route analysis by deletion.

| Route group | Decision | Evidence |
| --- | --- | --- |
| Canonical registry entries (8) | KEEP_CANONICAL | `web/api_registry.py` records planning, evaluation, revision, version, and context ownership; handlers remain registered. |
| Compatibility reads: quality report, continuity report, next chapter | KEEP_COMPAT | Registry entries, response mapper/header responsibility, frontend/API test references. |
| Deprecated internal producers: quality check, continuity check | KEEP_INTERNAL_PRODUCER | Registered routes and CLI/command/checker calls still create legacy evidence. Hidden primary UI does not remove this responsibility. |
| Other legacy-looking routes outside the registry | DEFER_INVESTIGATE | They were not moved into a deletion batch; no absence search was treated as proof. |

**Specific conclusion for `/api/quality-check` and `/api/continuity-check`:** neither is a deletion candidate. The former reaches `commands.quality_check_command`; the latter directly invokes the continuity checker and persists a compatibility report. Both have API/route tests and retained frontend functions. They are R4 internal producers until an approved evidence migration proves otherwise.

## 5. Frontend audit

* The template loads the primary application script, narrative evaluation, planning-control modules, revision center, memory/model/diagnostics/creative/analytics/author modules, and their related assets.
* The visible navigation contains one `#narrative-evaluation-center` entry. Quality and continuity buttons remain in the template but are hidden at runtime by `app.js`; the functions and their legacy routes remain bound.
* `window.storyosApiRequest` is used by the primary app, revision center, planning studio, and planning-control modules. The shared boundary handles project-switch request cancellation and JobManager polling cleanup.
* `planning-studio.js` is the only identified top-level static JavaScript file without a current template script tag. It is **not** a deletion candidate because a static request-isolation test reads it and earlier audit documentation records unresolved integration history. It is deferred rather than guessed away.
* No fully unreferenced frontend file or DOM region was proven with all required script, dynamic-load, event, deep-link, compatibility, and test evidence.

## 6. Storage and legacy-path responsibility

| Domain | Authority / active path | Legacy or history responsibility | Decision |
| --- | --- | --- | --- |
| Planning | `PlanningMutationService` -> `DataStoreWriteFacade` -> `DataStore` | next-chapter compatibility route and planning-control snapshots retain schema compatibility | Keep authoritative/compatibility paths. |
| Evaluation | `EvaluationService` reports and indexes | legacy quality/continuity report readers; producers may still write compatibility evidence | Keep analyzer and data readers. |
| Revision | `RevisionService` request/candidate/patch workflow | candidate and canon/archive historical reads | Keep active/history. |
| Version & adoption | `VersionWriterFacade` for work-version/index writes | `version_manager` names, scans, reads versions and selected pointer; archive paths | Keep compatibility/history. |
| Memory & context | `ContextAssemblyService` read-only package | state, Canon, summaries, vector retrieval, external sync projections | `DATA_RETENTION_DEFER`; no data deletion audit. |

No real `data/` directory is a deletion candidate. This audit did not inspect or emit novel body content.

### Historical `.bak` retention register

All entries are inside real `data/`, have a corresponding formal file, and may carry recovery responsibility. They are `DATA_RETENTION_DEFER`, not temporary cleanup.

| Backup | Created | Last modified | Formal counterpart | Decision |
| --- | --- | --- | --- | --- |
| `data/state.json.bak` | 2026-07-13T21:29:29 | 2026-07-15T01:21:13 | exists | DATA_RETENTION_DEFER |
| `data/story_blueprint.json.bak` | 2026-07-13T21:29:29 | 2026-07-15T01:21:13 | exists | DATA_RETENTION_DEFER |
| `data/author_profile/experiences.json.bak` | 2026-07-14T00:39:07 | 2026-07-15T01:19:04 | exists | DATA_RETENTION_DEFER |
| `data/creative_loop/health/history.json.bak` | 2026-07-14T18:39:08 | 2026-07-14T16:59:43 | exists | DATA_RETENTION_DEFER |
| `data/creative_loop/issues/index.json.bak` | 2026-07-14T18:39:08 | 2026-07-14T16:59:43 | exists | DATA_RETENTION_DEFER |
| `data/vector_index/metadata.json.bak` | 2026-07-14T09:53:14 | 2026-07-14T09:58:37 | exists | DATA_RETENTION_DEFER |

Canon, memory, vector, Obsidian/external-sync projections, historical versions, candidates, adoption audit, and real evaluation data likewise require a separately approved data-retention policy before any physical action.

## 7. Untracked-file and temporary-artifact audit

At baseline, `git ls-files --others --exclude-standard` listed **179 files**: **35 formal stage files** and **144 files below 14 pytest basetemp directories**. `git diff --stat` does not include these untracked paths.

| Group | Count | Classification | Rationale |
| --- | ---: | --- | --- |
| `core/contracts/` | 5 files | KEEP_ACTIVE | Stage 16 contracts and safety primitives. |
| `evaluation_engine/legacy_adapter.py` | 1 file | KEEP_DATA_READER | Compatibility routes and adapter tests. |
| `system/` stage services | 6 files | KEEP_ACTIVE / KEEP_COMPAT | Context, planning mutation, revision adapter, safe write, version adoption/writer services. |
| `web/api_registry.py`, `web/api_support.py` | 2 files | KEEP_ACTIVE | Canonical/compatibility ownership and shared pagination support. |
| `tests/` stage tests | 19 files | KEEP_TEST_INFRA | Contract, safety, facade, adapter, and isolation coverage. |
| Existing architecture docs | 2 files | Keep documentation | Stage 16 architecture evidence; not code deletion candidates. |
| pytest basetemp content | 144 files in 14 directories | TEMP_CLEANUP_CANDIDATE | Isolated test data, untracked, outside real `data/`; deletion still requires approval. |

### R0 temporary cleanup register

These directories are untracked test basetemps. Their names, creation/modification times, and contents are consistent with the named Stage 16 test runs. Each has no top-level `data` directory. Safe action, if later approved: remove only the listed directory by literal path after a fresh Batch 0 snapshot; do not use `git clean`.

| Directory | Created | Modified | Files observed | 16.4-B eligibility |
| --- | --- | --- | ---: | --- |
| `.pytest-tmp-phase-16-2-2c-commands-20260716-185453` | 2026-07-16T18:54:54 | 2026-07-16T18:54:54 | 40 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-2c-commands-20260716-185543` | 2026-07-16T18:55:44 | 2026-07-16T18:55:44 | 40 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-2c-final-20260716-185633` | 2026-07-16T18:56:35 | 2026-07-16T18:56:37 | 289 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-2c-mid-20260716-185355` | 2026-07-16T18:53:57 | 2026-07-16T18:53:59 | 260 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-2c-probe-20260716-185222` | 2026-07-16T18:52:23 | 2026-07-16T18:52:23 | 34 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-3-final-20260716-192223` | 2026-07-16T19:22:30 | 2026-07-16T19:22:46 | 734 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-3-final2-20260716-192314` | 2026-07-16T19:23:20 | 2026-07-16T19:23:37 | 734 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-final-20260716-194000` | 2026-07-16T19:51:06 | 2026-07-16T19:51:09 | 335 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-final2-20260716-195149` | 2026-07-16T19:51:50 | 2026-07-16T19:51:53 | 335 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-final3-20260716-195412` | 2026-07-16T19:54:13 | 2026-07-16T19:54:16 | 347 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-probe2-20260716-193405` | 2026-07-16T19:34:11 | 2026-07-16T19:34:16 | 131 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-probe3-20260716-193529` | 2026-07-16T19:35:35 | 2026-07-16T19:35:36 | 129 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-probe4-20260716-193625` | 2026-07-16T19:36:31 | 2026-07-16T19:36:35 | 131 | TEMP_CLEANUP_CANDIDATE |
| `.pytest-tmp-phase-16-2-4-probe5-20260716-193727` | 2026-07-16T19:37:32 | 2026-07-16T19:37:35 | 132 | TEMP_CLEANUP_CANDIDATE |

No unknown-source untracked file was found in the baseline listing. Cache/build/log locations, if later found, require their own literal-path register; none were cleaned or reclassified as data.

## 8. Documents and deferred questions

* `docs/architecture/story-os-engine-merge-map-16-1.md` remains the concise ownership/status map; this full evidence matrix remains here.
* `PHASE_14_0_PLANNING_AUDIT.md` documents the unmounted planning studio and is historical evidence, not proof that its script may be deleted.
* Before any R1/R2 deletion review, establish dynamic-script/deep-link/external caller evidence for `planning-studio.js` and explicit external compatibility sunset criteria for all five registry compatibility/deprecated routes.

## 9. Proposed 16.4-B batches (not executed)

### Batch 0 — protection and approval

Capture `git status --short`, `git diff --stat`, full untracked listing, and the three protected SHA-256 values again. List literal approved paths, confirm no real-data path is present, preserve the current diff, and obtain explicit user approval. Do not rely on reset, restore, or clean for rollback.

### Batch 1 — R0 temporary artifacts

Only after Batch 0 approval, remove a small, literal subset of the 14 registered pytest directories. Re-list the directory before each removal. Rollback is not applicable to generated test artifacts, but a failed scope check stops the batch immediately. Never include `data/**/*.bak`, `data/canon/**`, `data/memory/**`, evaluations, versions, candidates, or audits.

### Batch 2 — R1 internal symbols

No approved candidates. Do not start until a future audit produces a symbol with two independent no-reference evidence sources, a tested replacement, no storage/API/CLI compatibility responsibility, and an exact rollback patch.

### Batch 3 — R2 hidden UI or thin wrappers

No approved candidates. `planning-studio.js` and hidden quality/continuity controls remain excluded until deep-link, event, API-contract, and static-test responsibilities are cleared.

### Batch 4 — R3 compatibility routes/readers

Deferred by default. Requires renewed user approval plus verified external contract retirement, historical data read coverage, and migration/fallback evidence.

### Batch 5 — documentation and ignore policy

After physical work only, update the ownership/compatibility records and consider a separately approved `.gitignore` change that prevents future pytest basetemps entering the workspace. Do not modify `.gitignore` in 16.4-A.

## 10. Final regression plan for a future 16.4-B

Run only after an approved physical batch changes code or files:

1. `python -m compileall -q web system evaluation_engine planning_engine core`
2. `node --check` for each retained and changed JavaScript file.
3. Per-batch targeted tests: canonical/compatibility API, planning, evaluation, revision, adoption, version, context, frontend contracts/request isolation, storage ownership, and real-data protection.
4. Final serial regression with a never-reused basetemp: `python -m pytest -q -p no:cacheprovider --basetemp <unique-directory>`.
5. If the environment is already runnable, smoke the homepage, one Planning GET, one Evaluation GET, one Context GET, and one legacy compatibility GET without model calls. Browser checks are optional only when binaries already exist.
6. Recheck protected SHA values and confirm no Canon, Memory, Version, Vector, or Obsidian data changed. Any failure stops further deletion and restores only the current approved batch by its prepared patch/record, without overwriting existing uncommitted work.

## 11. 16.4-A completion decision

The read-only audit is complete. It establishes no code/frontend `DELETE_CANDIDATE`, fourteen R0 temporary cleanup candidates awaiting approval, a retention hold for all real-data backups/history, a concrete 16.4-B batch and rollback plan, and a final regression checklist. It does **not** authorize or execute 16.4-B.

## 16.4-BV final validation result (2026-07-16)

* User authorization remained limited to the fourteen literal pytest directories recorded in the R0 register. All fourteen had already passed literal-path, containment, reparse-point, Git-tracking, and root-level-data checks.
* Physical cleanup was **not** executed: the execution environment rejected the exact `Remove-Item -LiteralPath` command before it started. The fourteen authorized paths still exist. There are 44 physical `.pytest-tmp-phase-16-*` directories; the other 30 were not authorized and were not touched. Physical cleanup is deferred to **16.4-BC** in an authorized environment.
* The actual Git root is `D:\novel\StoryOS`. Its `.gitignore` now contains only the narrow project-root rule `/story-os-demo/.pytest-tmp-phase-*/` for this purpose. `git check-ignore --no-index` confirms the rule for `story-os-demo/.pytest-tmp-phase-16-probe/`; it does not match `story-os-demo/tests/`. The pre-existing `data/` rule, not the new rule, ignores paths below `story-os-demo/data/`.
* Static verification passed: `D:\novel\StoryOS\.venv\Scripts\python.exe -m compileall -q web system evaluation_engine planning_engine core commands.py main.py`, and `node --check` passed for all nine Stage 16 first-party JavaScript files listed in the 16.4-BV instruction.
* The selected targeted pytest process used a unique system-TEMP basetemp and completed, but its terminal session did not provide a final summary to this runner. It is not recorded as a passing gate.
* The serial full pytest used `C:\Users\ta\AppData\Local\Temp\storyos-pytest-phase-16-4bv-full-20260716-210110`. Its captured progress contained one failure marker at approximately 23%; the process subsequently exited after the runner session lost the final pytest summary. No reliable failed-test name, traceback, counts, duration, or exit code was available. Therefore full regression is **not passed** and 16.4-BV is not complete. No diagnostic rerun or code/test change was made.
* HTTP smoke was not run because the full-regression gate did not pass. No model, vector, Obsidian, Canon, Memory, Version, Candidate, EvaluationReport, or real-data operation was executed by this validation stage.
* The three protected SHA-256 values remain the audit baseline; the six real-data `.bak` entries remain present and unmodified. `DELETE_CANDIDATE` remains `0`; `planning-studio.js` remains `DEFER_INVESTIGATE`.

## 16.4-BV-R1 auditable full-regression result (2026-07-16)

* Test result directory (outside the repository): `C:\Users\ta\AppData\Local\Temp\storyos-phase-16-4bv-r1-final`. The authoritative artifacts are `pytest-stdout.log`, `pytest-stderr.log`, and `pytest-junit.xml`; no result artifact was written to the repository.
* Full command: `D:\novel\StoryOS\.venv\Scripts\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider --basetemp=<resultRoot>\pytest-temp --junitxml=<resultRoot>\pytest-junit.xml`.
* Result: exit code `1`; JUnit XML exists; `610` tests total, `1` failure, `0` errors, `1` skipped, `608` passed, duration `73.93s`. Stdout contains the normal pytest final summary, so this is not an output-session or collection-infrastructure failure.
* Failing node id: `tests/test_data_recovery_tool.py::test_inventory_excludes_pytest_temporary_directories`.
* First key error: `inventory([source], {"story_blueprint": "", "next_chapter_plan": ""})` returned one filesystem candidate under the system-TEMP pytest basetemp instead of `[]`. The candidate points to `...\pytest-temp\test_inventory_excludes_pytest0\source\story_blueprint.json`.
* One permitted diagnostic rerun used `<resultRoot>\diagnostic-temp` and reproduced the same assertion failure with exit code `1` in `0.19s`. This is a stable code/test behavior failure in pytest-temporary-directory exclusion, not a physical-cleanup, Windows lock, or output-session failure. No code or test was changed.
* HTTP smoke was not run because the full regression failed. Protected SHA values and the six real-data `.bak` entries were rechecked after testing. Physical cleanup remains deferred to 16.4-BC; all fourteen authorized directories and the thirty unauthorized directories remain untouched.

## 16.4-BV-F1 Data Recovery pytest-directory exclusion and final regression (2026-07-16)

* Root cause: `tools/data_recovery.py::inventory()` only excluded `.pytest*` path components while walking discovered files. That covered repository-local dot directories, but it neither recognized pytest's system-TEMP structures nor rejected an excluded scan root before traversal. A `story_blueprint.json` below a Story OS pytest basetemp was therefore read as a recovery candidate.
* Minimal repair: `_is_pytest_temporary_path()` now normalizes path components without resolving them and recognizes only `.pytest-tmp-phase-*`, the default `pytest-of-*/pytest-<number|current>` hierarchy, `storyos-pytest-*`, and the Story OS `storyos-phase-*/pytest-temp` or diagnostic-temp layout. `_allowed()` applies this before file reads and `os.walk(..., followlinks=False)` prunes matching directories. Symlink roots/files are not followed. The recovery result schema and public method signature are unchanged.
* Mis-exclusion guard: a regression test proves that project paths named `pytest-novel-project` and `temporary-kingdom` are not classified as pytest temporary paths. The implementation does not exclude all system TEMP, generic `pytest`, `test`, `temp`, `storyos`, or `recovery` names, and has no username or fixed-drive dependency.
* Directed validation passed: py_compile; the original failure (`1 passed`); `tests/test_data_recovery_tool.py` (`7 passed`); `tests/test_real_data_protection.py` (`2 passed`); and the required core compileall command. The three protected JSON SHA-256 values remained unchanged.
* Auditable full regression ran once with a never-reused basetemp and log/JUnit artifacts outside the repository. Exit code `0`; pytest summary `610 passed, 1 skipped in 62.51s`; JUnit `tests=611`, `failures=0`, `errors=0`, `skipped=1`, `time=62.491s`. The one skip is the Windows-host symlink capability skip in `tests/test_project_ref.py`.
* HTTP smoke was not run: the repository has safe per-test TestClient fixtures, but no single standalone, explicitly real-project-isolated harness that covers all required homepage, Planning, Evaluation, Context, and legacy GETs without setup writes. This is non-blocking. No model call occurred.
* Physical pytest-directory cleanup remains deferred to 16.4-BC. All 44 physical directories remain, including the 14 user-authorized-but-environment-blocked directories; no deletion was retried. `DELETE_CANDIDATE` remains `0`.
