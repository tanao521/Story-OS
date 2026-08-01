# Story OS — Phase 0D8-FV Delivery Report

## Current authoritative SEAL summary

Final conclusion:

**SEALED - PHASE 0D8 COMPLETE**

| Slice | Current result |
|---|---|
| 0D8-A | PASS |
| 0D8-B | PASS |
| 0D8-C | PASS |
| RC1 | PASS |
| RC2 | PASS |
| RC3 | PASS |
| RC4 | PASS |
| Gate 4 | PASS |
| Phase 0D8-FV | PASS |

Next product phase: **NOT AUTHORIZED**

Earlier `PARTIALLY PASSED`, `BLOCKED`, and `REPAIR REQUIRED` statements in
dated sections below are historical checkpoints. They are preserved as
evidence and do not describe the current phase state.

## Historical opening conclusion (superseded)

**PARTIALLY PASSED — VERIFICATION INCOMPLETE.**

The 0D8-A/B/C authority implementation passed the focused and affected
matrices. A fresh isolated browser run completed the manual X → request
changes → distinct Y → fresh Y approval → strict approved Commit path, and
the durable Commit and canonical provenance matched the exact Y approval.

Phase 0D8-FV is not eligible for `PASSED — READY FOR PHASE 0D8-SEAL
AUTHORIZATION` because the full browser race/drift matrix was not independently
closed through the visible UI, and the first full-suite run had one unrelated
non-0D8 failure. A second full-suite run passed. No production repair was made.

## Baseline integrity audit

- Working tree was already dirty before FV. It contained the 0D8-C production
  baseline, 0D8-A/B/C tests and reports, and unrelated earlier StoryOS changes.
- No commit, push, PR, SEAL, roadmap mutation, Provider call, dependency change,
  or production edit was made during FV.
- 0D6 and 0D7 sealed authority files were not reopened.
- Provider, Canon, vector, memory, and multi-timeline boundaries were not
  expanded.
- Runtime observed: Python 3.14.5, Node v24.14.0, npm 11.9.0, pytest 9.1.1,
  Windows 10.0.26200. Symlink capability was not conclusively re-run because
  the host probe was blocked by the shell safety wrapper; no symlink test was
  weakened or skipped by FV.

## 0D8-A/B/C authority reconciliation

The focused exact-version, lineage, and approval-to-Commit tests passed.
Coverage included immutable X/Y identity, fingerprint freshness, selection
drift, invalid/conflicting authority, rejected/request-changes states, failed
mutation prevention, exact provenance, and duplicate replay.

| Invariant | Result |
|---|---|
| Approval of X never approves Y | PASS in service/API matrix; visible browser cross-version isolation not independently closed |
| X → Y lineage is durable and immutable | PASS |
| Y requires fresh review | PASS |
| Approved identity equals committed identity | PASS |
| Approved fingerprint equals committed fingerprint | PASS |
| Decision ID consumed by Commit equals persisted approval ID | PASS |
| Selection drift cannot retarget Commit | PASS in service/API matrix |
| Content drift invalidates Commit eligibility | PASS in service/API matrix |
| Missing/rejected/stale/invalid/conflicting authority fails closed | PASS in service/API matrix |
| Evidence cannot authorize Commit | PASS |
| Lineage cannot authorize Commit | PASS |
| Failed validation produces no Commit mutation | PASS |
| Duplicate replay creates one durable Commit | PASS in service/API matrix |
| Legacy compatibility cannot bypass strict authority | PASS in affected matrix |

## Test results

- 0D8 focused matrix: **40 passed, 0 failed**.
- Affected 0D7/0D8/review/version/Commit/Revision matrix: **147 passed, 0
  failed**.
- Test collection: **2471 collected, 0 collection errors**.
- Full suite run 1: **2470 passed, 1 failed, 0 skipped**. The failure was
  `tests/test_phase0d4e1_branch_process.py::test_real_process_restore_vs_select_keeps_lifecycle_and_activity_separate`.
- The failed test was rerun alone and passed: **1 passed**.
- Full suite run 2: **2471 passed, 0 failed, 0 skipped**, in 249.04 seconds.
- Full-suite warnings: two pre-existing `PytestUnknownMarkWarning` warnings for
  `pytest.mark.timeout` in `tests/test_phase0c2_rc2_vr.py`; no unexplained skip.
- The first-run failure is an unrelated, nondeterministic earlier-phase
  cross-process branch race; it is not in the 0D8 production or test scope.

## Browser scenario ledger

Fresh isolated local fixture and browser tab were used. No Provider, external
network, credentials, or real project was used.

- Opened exact `manual_v001` X and inspected its visible version/fingerprint
  state.
- Requested changes for X through the visible UI.
- Created distinct manual `manual_v006` Y through the visible editor.
- Selected and opened Y; the UI reported `Human decision: MISSING` before the
  fresh approval.
- Created fresh APPROVED authority for Y through the visible UI.
- Cancelled the optional AI-polish branch and continued the manual Commit path.
- Commit succeeded and `已提交到第1章` became visible.
- The first approval attempt with optional polish was deliberately recorded as
  a fixture/provider-path warning; it did not create a Commit mutation.
- Selection-drift, content-drift, invalid/conflicting authority, delayed
  response, rapid-switch, and duplicate-replay cases were covered by the
  focused/API matrices, but were not all independently driven as visible
  browser scenarios. This is the remaining FV gap.

## Successful exact Commit identities

From the isolated fixture persisted records:

- Project: `phase0d7fv_browser_nf67pw9o`
- Timeline/branch/chapter: `main` / `main` / `1`
- Revision transition: `review_transition_efb8b600f4134234af525b901997ceb4`
- Y source version: `manual_v006`
- Approval decision consumed: `review_decision_888ff6fbaf704b2ea82e492aefff801c`
- Decision type/status: `APPROVED` / `CURRENT`
- Source fingerprint: `84eef1dc5bce5b70e68630a9c371bd07733301e41182ab371764cf47085d38dc`
- Commit ID: `8a462627ff39f761`
- Canon revision: `canon-chapter-001-v001`
- Canon provenance revision identity: `commit_4bdce2dad19e4b608530830b5deee9a4`

The Commit run and canonical index both persisted the same project, timeline,
branch, chapter, source type, Y version, fingerprint, decision ID, decision
type, decision status, decision timestamp, and validation timestamp.

## Provenance and safety audit

- Commit run status was `completed_with_warnings`; all core Commit mutations
  (Canon revision, chapter projection, summary, state, and memory index) were
  successful.
- Canonical revision provenance matched the Commit run provenance exactly.
- Historical X → Y transition data remained readable after Commit.
- Failed authority cases in the focused matrix created no Commit-side or
  canonical mutation.
- Post-Commit fixture warnings were limited to unavailable compatibility
  integrations: Version archive import mismatch, Obsidian signature mismatch,
  reflection job import mismatch, planning-anchor signature mismatch, and
  `VECTOR_SCOPE_REQUIRED`. These did not alter the authority identity or the
  successful core Commit result and are outside the 0D8 FV production freeze.

## Static and asset checks

- Python compilation/import check for changed 0D8 modules and tests: passed.
- `node --check web/static/app.js`: passed.
- `git diff --check`: passed; only existing CRLF normalization warnings were
  emitted.
- Test collection: passed.
- Browser loaded the current disk JavaScript and template assets during the
  isolated local run; no production browser asset was changed during FV.

## Production-freeze verification

Production diff during FV: **zero**. Only this verification report was added;
no production file, test assertion, fixture helper, or browser harness was
modified during the run.

## Cleanup ledger

- Owned `uv`/Python fixture server processes: stopped and verified absent.
- Owned browser tab: closed and browser session finalized.
- Two FV-created temporary fixture projects: removed using exact containment-
  checked paths.
- Unrelated browser processes and pre-existing temporary fixtures: untouched.
- No FV residue was left in the repository.

## Remaining risks and recommended next action

The remaining gap is verification scope, not a demonstrated 0D8 authority
bypass: independently drive the selection-drift, content-drift, delayed
response, rapid-switch, and duplicate-replay scenarios through a fresh visible
browser harness, then rerun the full suite once more if the harness changes.

Do not begin 0D8-SEAL from this report. A separate FV continuation or narrowly
scoped browser-verification authorization is required before declaring
`PASSED — READY FOR PHASE 0D8-SEAL AUTHORIZATION`.

## Phase 0D8-FV continuation — visible browser drift/race/replay closure (2026-08-01)

### Continuation scope and environment

This continuation remained limited to Phase 0D8-FV. Execution used one agent,
medium effort, a fresh isolated local fixture, the real FastAPI routes, the
real production version/review/transition/Commit services, and the visible
Story OS browser UI. No production file was edited. The tests-only fixture
helper `tests/_phase0d8fv_continuation_fixture_server.py` was added to create
fresh X/Y/Z versions and to hold selected response paths for race testing.
The fixture was corrected so its Y and Z content met the existing minimum
content-length contract; this was test-only setup work.

The baseline audit recorded the existing dirty worktree and the frozen 0D8
production files as pre-existing changes. Python 3.14.5, Node v24.14.0,
pytest 9.1.1, Windows 11 build 26200, and ports 7865–7869 were checked. The
fixture server ran on 7867 with current disk assets and a request JSONL audit
log. Six continuation-owned temporary fixture directories were removed at
cleanup.

### Visible browser evidence

The browser reached the current local app and the visible version panel
reported `manual_v001` through `manual_v007`, with Y represented by
`manual_v006`. A real visible rapid-switch sequence issued these selection
requests, in order, as captured by the fixture request log:

`manual_v007` → `manual_v001` → `manual_v006`.

The browser then hit a selector deadline while attempting to obtain the final
visible state. Its tab screenshot/state also degraded into an abnormal data
page, so the final selected version, displayed authority attribution, and
post-switch Commit result could not be independently audited. This is an
environment/browser gate failure, not evidence of a production authority
bypass.

| Visible gate | Result | Evidence or limitation |
|---|---|---|
| Selection drift | INCOMPLETE | Version panel visible; final settled DOM unavailable after timeout |
| Content drift | NOT EXECUTED | No trustworthy visible post-mutation state |
| Cross-version isolation | NOT EXECUTED | No trustworthy visible post-mutation state |
| Delayed decision response | NOT EXECUTED | Browser state became unauditable before release/settle proof |
| Delayed transition response | NOT EXECUTED | Same environment gate |
| Delayed Commit response | NOT EXECUTED | Same environment gate |
| Rapid switching | PARTIAL | Request log proves v007 → v001 → v006 dispatch; final DOM not proven |
| Duplicate replay | NOT EXECUTED | No visible retry/replay proof |
| Invalid/conflicting authority | NOT EXECUTED | No visible fail-closed proof |

The traditional visible UI also does not expose an independent strict Commit
button separate from its approval/polish flow; this prevents claiming an
attribution-safe Commit scenario from hidden API calls when the browser state
is already unstable.

### Regression and static validation

- Focused matrix: **40 passed**.
- Affected matrix: **147 passed**.
- Full-suite rerun was started because the tests-only fixture changed, but did
  not produce a valid result within 180 seconds and exited with
  `OSError: [Errno 22] Invalid argument` while flushing pytest stdout. It is
  therefore **not counted as passed**.
- Fixture Python compilation, `node --check web/static/app.js`, and
  `git diff --check`: passed; only existing line-ending warnings were emitted.
- No production diff was introduced by this continuation.

### Cleanup and final disposition

Owned browser tabs were closed and the browser session finalized. Owned
fixture server processes and all six continuation fixture directories were
removed; no continuation fixture directory remained. Unrelated browser
processes and unrelated temporary state were not touched.

Final continuation status: **PARTIALLY PASSED — VERIFICATION INCOMPLETE**.
The API/regression evidence remains green, but the visible browser gates for
drift, delayed responses, replay, and invalid/conflicting authority remain
unclosed because the browser environment could not provide a stable,
auditable final state. Do not authorize 0D8-SEAL from this continuation.

## Phase 0D8-FV final verification closure attempt — stable browser harness (2026-08-01)

### Execution configuration and harness stabilization

Execution used one agent at medium effort. No sub-agents, production edits,
Git writes, Provider calls, or external credentials were used. The browser
surface was the in-app Browser, with one fresh product tab and one fixture
server at a time. The fixture used port 7867 and produced a fresh isolated
project. Control endpoints were kept separate from the product tab; no control
request navigated the product tab.

The browser binding ID, tab ID, fixture PID/port/project, product URL, smoke
DOM state, and bounded failure are retained in
`.tmp/phase0d8fv-harness/browser-smoke.json`. The in-app Browser surface did
not expose an executable path, profile path, or CDP endpoint; this limitation
is recorded there rather than guessed.

The smoke test reached `Story OS Web Console`, found one manual-version list,
read visible versions `manual_v001` through `manual_v007`, and read the
selected pointer as `manual_v006`. After the page was inspected, the seven
version action buttons were present in the DOM, but bounded visible clicks
consistently exceeded their deadline. DOM CUA scrolling/clicking also caused
the browser tool to report an abnormal data-page screenshot state. The tab was
closed and the browser session finalized immediately; no scenario was driven
after the state became unauditable.

### Serial browser ledger

| Scenario | Result | Final-state / mutation evidence |
|---|---|---|
| Harness smoke | PARTIAL | Product URL/title, seven visible version identities, selected `manual_v006`; action interaction unstable |
| Rapid switch | BLOCKED | Not started after smoke gate; no final Y DOM claim |
| Delayed decision response | BLOCKED | Not started |
| Delayed transition response | BLOCKED | Not started |
| Cross-version approval isolation | BLOCKED | Not started; no Commit/Canon mutation |
| Selection drift | BLOCKED | Not started; no Commit/Canon mutation |
| Content drift | BLOCKED | Not started; no H1/H2 visible authority proof |
| Invalid/conflicting authority | BLOCKED | Not started; no visible taxonomy proof |
| Delayed Commit response | BLOCKED | Not started; no durable operation attribution claim |
| Duplicate Commit replay | BLOCKED | Not started; no browser transport replay claim |

No visible browser scenario produced a Commit or Canon mutation in this
attempt. This is an environment block, not a reproduced production defect.
The earlier API/focused evidence remains historical and is not substituted for
these missing visible gates. Strict-path and legacy-bypass behavior therefore
remains supported by the existing 0D8 API/contract matrices, but is not newly
closed through this browser attempt.

### Regression execution and evidence files

The focused and affected matrices were rerun after the harness attempt:

- Focused: **40 passed**.
- Affected: **147 passed**.
- Collection: **2471 tests collected**.
- Full suite command: `uv run python -m pytest -q`.
- Full suite: **2471 passed, 0 failed, 0 skipped**, exit code 0, normal pytest
  exit, in 228.90 seconds (`2026-08-01T16:18:46.7737497+08:00` to
  `2026-08-01T16:22:36.8783247+08:00`). Two pre-existing unknown-mark warnings
  were emitted.
- Full-suite stdout: `.tmp/phase0d8fv-harness/full-suite.stdout.log`.
- Full-suite stderr: `.tmp/phase0d8fv-harness/full-suite.stderr.log`.
- Full-suite summary: `.tmp/phase0d8fv-harness/full-suite.summary.json`.
- Browser smoke evidence: `.tmp/phase0d8fv-harness/browser-smoke.json`.

Fixture Python compilation, JavaScript syntax validation, and `git diff
--check` passed. The served `web/static/app.js?v=12` SHA256 matched the disk
file exactly:

`B1C1AD82B2C85439A6A68EDEC08A6D401C1F881B689561ACDEC3626C29C3FF9F`.

The comparison is retained in `.tmp/phase0d8fv-harness/asset-sha.json`.

### Cleanup and production freeze

The owned browser tab/session, fixture server process tree, and isolated
fixture projects were stopped/removed. No continuation fixture directory
remained in the system temporary directory. The declared evidence directory
`.tmp/phase0d8fv-harness` intentionally retains pytest logs, asset evidence,
and the browser smoke record; no unrelated process or directory was touched.

The working-tree audit shows the same pre-existing StoryOS dirty baseline and
0D8 production files; this continuation introduced no production-file change.
No commit, push, PR, SEAL, roadmap change, provider change, dependency change,
or production repair was performed.

### Final conclusion and SEAL readiness

Final status: **BLOCKED — BROWSER VERIFICATION ENVIRONMENT NOT STABLE**.

The final full-suite regression gate is now closed, and all recorded API/static
regression evidence remains green. The required visible browser drift/race/
replay gates are not closed because the browser harness again became
unauditable at the first interaction boundary. This continuation must not be
declared `PASSED — READY FOR PHASE 0D8-SEAL AUTHORIZATION`; 0D8-SEAL remains
blocked pending a stable browser execution environment.

## Final browser closure — 2026-08-01 (Resume 0D8-FV)

This dated section records the resumed verification. The authorized scope
remained Phase 0D8-FV; no 0D8-SEAL, commit, push, PR, production repair,
dependency change, or roadmap/provider change was performed. The production
freeze list was respected. Only tests-only browser fixtures/runners, declared
evidence, and this report append were changed.

### Execution and evidence

- Acceptance browser: fresh local Microsoft Edge/CDP sessions, one isolated
  profile and fixture workspace per scenario, serial execution on loopback
  port 7867. The unstable in-app Browser was not used for acceptance.
- Evidence root: `.tmp/phase0d8fv-final-browser/`.
- The corrected smoke path reached the real console, title `Story OS Web
  Console`, seven visible version actions, and selected `manual_v006`.
- The first rapid-switch attempt used list indexes and is diagnostic only. The
  accepted rerun used exact visible identities `manual_v001` → `manual_v006` →
  `manual_v007` → `manual_v006`.

### Serial browser ledger

| Scenario | Result | Browser evidence and mutation result |
|---|---|---|
| Smoke | PASS (BH1 baseline) | Stable Edge/CDP console and visible version controls. |
| Rapid switching | PASS | Final DOM was exact Y (`manual_v006`) after delayed X release; request/response order retained; 0 `commit_runs`, 0 `canon_revisions`. |
| Delayed decision response | PASS | X decision held/released while Y became final; final preview/transition remained Y; no commit/canon mutation. |
| Delayed transition response | PASS | Transition held/released across X→Y switching; final state remained Y; no commit/canon mutation. |
| Cross-version approval isolation | INCOMPLETE | Pending-Y fixture showed a visible legacy approved projection while the affected Y action could not be proved independently; no mutation occurred. |
| Selection drift | INCOMPLETE | Z preview changed while selected pointer/review identity remained Y and showed `STALE`; no independently attributable strict Commit action; no mutation. |
| Content drift | PASS | Fixture mutated Y content; reopened Y showed changed content and `Human decision: STALE`; no commit/canon mutation. |
| Invalid authority | FAIL-CLOSED / INCOMPLETE | Malformed authority produced zero visible version actions and zero mutations; exact affected-version taxonomy was unavailable. |
| Conflicting authority | FAIL-CLOSED / INCOMPLETE | Conflicting authority likewise produced zero visible actions and zero mutations; exact affected-version proof is missing. |
| Delayed Commit response | INCOMPLETE | Visible approve flow issued observed `POST /api/review/approve` requests, but no durable commit/canon row was created; selection became `无` after switching/release. |
| Duplicate Commit replay | NOT EXECUTED | No successful visible strict Commit existed from which to perform a browser transport replay; unit/API evidence was not substituted. |

Control operations were fixture-only hold/release/mutate/read endpoints and did
not navigate or mutate the product tab. Passing drift scenarios show no
non-GET product mutation. No legacy fallback was observed, but strict-path
parity and replay provenance cannot be claimed without a successful visible
strict Commit.

### Regression, static, and asset gates

- Focused 0D8 matrix: **40 passed** (`.tmp/phase0d8fv-final-browser/focused.log`).
- Related expanded matrix: **163 passed**. This is broader than the
  historical authorized 147-test selection; the historical baseline remains
  the prior **147 passed** result.
- Full collection: **2471 tests collected**, no collection error.
- The authoritative prior full suite remains **2471 passed, 0 failed, 0
  skipped, 228.90 seconds**; it was not rerun because no collected
  production/test implementation was changed in this continuation.
- Python compile, `node --check web/static/app.js`, and `git diff --check`
  passed. Logs are under `.tmp/phase0d8fv-final-browser/`.
- Served and disk `web/static/app.js?v=12` SHA256 matched:
  `b1c1ad82b2c85439a6a68edec08a6d401c1f881b689561acdec3626c29c3ff9f`.
  Evidence: `.tmp/phase0d8fv-final-browser/asset-sha.json`.

### Cleanup and conclusion

Owned Edge/CDP processes, fixture servers, profiles, and scenario workspaces
were cleaned. The stale exact directory
`phase0d8fv_continuation_f_r73jsl` was removed after containment verification;
ports 7867 and 7868 were confirmed free. Historical evidence directories
`.tmp/phase0d8fv-harness` and `.tmp/phase0d8fv-bh1` were preserved.

Final status: **PARTIALLY PASSED — VERIFICATION INCOMPLETE**.

Visible drift/race/content-stale and fail-closed observations are recorded,
but duplicate Commit replay, strict visible Commit attribution, and the
selection/delayed-Commit closure remain open. No production defect was
reproduced and no production fix is authorized by this run. Do not enter
0D8-SEAL; a future run must first provide a stable, independently visible
strict Commit path and then close replay/provenance with fresh isolated
browser evidence.

## Strict visible Commit closure — 2026-08-01 (Resume 0D8-FV)

This section records the narrowly authorized strict-Commit continuation. The
production freeze remained active: no production file, dependency, Provider,
roadmap, Canon authority, non-main timeline, commit, push, PR, or 0D8-SEAL
action was performed. New evidence is retained under
`.tmp/phase0d8fv-strict-commit/`.

### Gate 0 — strict visible Commit baseline

Two fresh isolated Edge/CDP fixtures passed the baseline independently. The
visible sequence was exact Y (`manual_v006`) already carrying a fresh
APPROVED decision, visible Y selection/open, visible approval, cancellation of
the optional AI-polish dialog, and the real no-polish POST.

The audited network and runtime path was:

```text
POST /api/review/approve {force:false,polish:null}
POST /api/review/approve {force:true,polish:false}
ChapterCommitService.commit_chapter(..., approved_identity=Y,
    approval_decision_id=Y decision ID)
validate_approved_commit(Y identity, Y decision ID)
CommitRunStore + RevisionService canon write
```

No direct legacy `commit_chapter` call without immutable approval identity was
observed, and no fallback to the legacy authority path was observed. The
tests-only runtime audit recorded the exact Y source version, fingerprint and
decision ID at both the commit entry and strict authority validation.

Each fresh run produced exactly one Commit run and one Canon index/revision.
The shared provenance fields matched:

| Field | Gate 0 result |
|---|---|
| source version | `manual_v006` |
| source fingerprint | `017b2a88ba37d8bf0683d390bfa3ab85c34f7468c5a99fe00769a82fb0730a47` |
| decision type/status | `APPROVED` / `CURRENT` |
| decision ID | equal in approval, Commit and Canon records |
| Commit ID | equal to Commit run record |
| Canon revision ID | `canon-chapter-001-v001` |

The visible completion log stated that the chapter was submitted, while the
visible review transition retained exact Y identity and fingerprint. After
successful archival the selected pointer became empty and manual actions were
removed; this was captured as post-commit UI state, not treated as a second
Commit. Evidence: `gate0-run-2.json` and `gate0-run-3.json`.

### Gate 1 — cross-version approval isolation

PASS. In a fresh pending-Y fixture, opening and selecting Y showed:
`Revised from manual_v001 · Fresh review required · no decision inherited
(STALE)`. Y had no exact APPROVED decision, no Commit-capable mutation was
performed, and persisted mutation counts were zero. The previously observed
legacy projection ambiguity is therefore disambiguated for the real visible
Y state: the current UI displayed the fail-closed fresh-review message and did
not inherit X authority.

Evidence: `cross-version-isolation.json`.

### Gate 2 — selection drift: production defect reproduced

The real visible `选择` action was used, not merely opening a preview:

```text
select Y → open Y → select Z
```

Before drift, Y was visibly selected and its exact approved transition was
shown. After selecting Z, the selected pointer and review target both changed
to `manual_v007`, but the preview metadata and preview text remained
`manual_v006` / Version Y. The required identity invariant therefore failed:

```text
preview identity = Y
selected pointer = Z
review target     = Z
```

No Commit or Canon mutation occurred. The observable frontend path is
`selectVersion()` → `POST /api/versions/select` → `refreshAll()`; the current
view is not reloaded or cleared when the selected identity changes, which is
consistent with the reproduced stale-preview mismatch. This is a real
production selection/display defect, not a fixture-only failure.

Evidence: `selection-drift.json`.

### Stop-rule application

Per the authorized Gate 2 stop condition, Gate 5 invalid/conflicting exact
taxonomy, Gate 3 delayed Commit response, and Gate 4 duplicate Commit replay
were **not executed**. Continuing would create a false drift setup because
preview, selection, and review identity do not converge. No replay or delayed
Commit claim is made from this run.

### Validation and cleanup

- Focused matrix: **40 passed**.
- Expanded related matrix: **163 passed**.
- Collection: **2471 tests collected**, 0 collection errors.
- Full suite rerun was required because an imported underscore helper changed:
  **2471 passed, 0 failed, 0 skipped, 231.16 seconds**; two pre-existing
  unknown-mark warnings remained.
- Python compilation, Node syntax check and `git diff --check` passed.
- Served/disk `web/static/app.js?v=12` SHA256 matched:
  `b1c1ad82b2c85439a6a68edec08a6d401c1f881b689561acdec3626c29c3ff9f`.
- Owned fixture servers, Edge profiles and temporary scenario directories were
  cleaned; ports 7867 and 7868 were free. Historical evidence directories
  `.tmp/phase0d8fv-harness`, `.tmp/phase0d8fv-bh1` and
  `.tmp/phase0d8fv-final-browser` were preserved.

### Final conclusion

Final status: **PARTIALLY PASSED — REPAIR REQUIRED**.

Gate 0 strict visible Commit and Gate 1 approval isolation are closed. Gate 2
reproduced a production selection/display defect: selecting Z leaves Y in the
visible preview while the selected pointer and review target identify Z. Gate
5/3/4 remain unexecuted by rule. Do not enter 0D8-SEAL. A separate repair
authorization is required for the selection identity convergence defect before
remaining replay and delayed-response gates can be validly executed.

## Phase 0D8-FV continuation: authority taxonomy stop evidence

This continuation was authorized against the accepted RC1 baseline. The
production freeze remained active. Only underscore-prefixed browser/fixture
helpers, isolated evidence, and this report were touched in this continuation.

### Gate 5 execution order and stop result

The first two malformed-authority cases were executed in fresh isolated
fixtures:

| Case | Visible taxonomy | Strict path | CommitRun/Canon | Result |
|---|---|---|---|---|
| malformed decision | `INVALID` | `validate_approved_commit` invoked and rejected | `0 / 0` | fail-closed |
| conflicting history | `CONFLICTING` | `validate_approved_commit` invoked and rejected | `0 / 0` | fail-closed |
| decision-ID mismatch | mismatch injected into the seeded Y decision | a new approval was created, then strict Commit accepted it | `1 / 1` | **STOP: authority bypass** |

Evidence:
`.tmp/phase0d8fv-final-gates/malformed-decision.json`,
`.tmp/phase0d8fv-final-gates/conflicting-decision.json`, and
`.tmp/phase0d8fv-final-gates/decision-id-mismatch.json`.

The malformed and conflicting cases also showed a legacy review-status label
of `approved`, while the exact transition and audit log reported
`APPROVAL_INVALID` or `APPROVAL_CONFLICTING`. That projection is ambiguous but
did not authorize a durable mutation in either case. The decision-ID mismatch
case is different and is blocking: after the seeded Y decision was changed to a
mismatched ID, the visible approval flow created a replacement APPROVED
decision and proceeded through the strict path. The audit recorded
`commit_chapter` followed by `validate_approved_commit`; persisted state
contained one CommitRun and one Canon index/revision. This satisfies the
authorized stop condition that inconsistent authority must not enable Commit.

The remaining Gate 5 fingerprint-mismatch case, Gate 3 delayed Commit
response, and Gate 4 duplicate Commit replay were **not executed** after this
blocking result. No claim is made for those gates, and 0D8-SEAL was not
entered. A production repair authorization is required before resuming.

### Continuation validation

- The final-gates runner and fixture compiled successfully with `py_compile`.
- No production file was changed during this continuation.
- The previously accepted RC1 focused, expanded, and full-suite results remain
  the authoritative regression baseline; no collected pytest test was added in
  this continuation.
- The isolated fixture process, browser profile, and temporary workspace were
  cleaned after the blocking scenario.

### Continuation conclusion

Final status remains **PARTIALLY PASSED — REPAIR REQUIRED**. The new blocker is
an authority-taxonomy closure defect: the approval endpoint can replace a
tampered decision during the visible approval flow, allowing Commit to proceed
with newly minted authority. Remaining replay and delayed-response evidence
must wait for an explicitly authorized production repair and a fresh serial
run.

## Phase 0D8-FV final-closure attempt: Gate 5 fingerprint mismatch stop

### Execution configuration and setup correction

This run resumed only the remaining FV gates under the explicit production
freeze. A fresh Edge/CDP fixture, fresh project, fresh temporary profile, and
loopback request ledger were used. Evidence is under
`.tmp/phase0d8fv-final-closure/`.

The first fingerprint fixture attempt was setup-invalid: its tests-only
control changed the persisted decision fingerprint to a synthetic value but
did not change authoritative Y content. It is retained only as diagnostic
evidence in `gate5-fingerprint-mismatch.json` and is not used for a gate
conclusion. The control was corrected without production changes to keep the
decision at H1 while changing Y content to H2.

### Gate 5 fingerprint mismatch — STOP / REPAIR REQUIRED

Corrected evidence:
`.tmp/phase0d8fv-final-closure/gate5-fingerprint-mismatch-corrected.json`.

Required precondition was satisfied:

```text
persisted Y approval fingerprint H1:
017b2a88ba37d8bf0683d390bfa3ab85c34f7468c5a99fe00769a82fb0730a47
authoritative Y content fingerprint H2:
72ab62adf6b3e84fd23527fba9c95a95f903c454ae256aeb27781c2e40496a4b
H1 != H2
```

The actual request sequence was:

```text
POST /api/review/approve {"force":false,"polish":null}
POST /api/review/approve {"force":true,"polish":false}
```

Actual result:

- Y visibly rendered as `STALE` before approval.
- The visible approval flow created a replacement APPROVED decision.
- Strict audit recorded `commit_chapter` followed by
  `validate_approved_commit`.
- CommitRun count: `1`.
- Canon index/revision count: `1`.
- Committed source fingerprint: H2
  (`72ab62adf6b3e84fd23527fba9c95a95f903c454ae256aeb27781c2e40496a4b`).
- CommitRun and Canon provenance matched each other, but the operation
  incorrectly converted the existing H1 approval/content mismatch into new
  H2 authority in the same visible operation.

This violates the authorized invariant that fingerprint mismatch must fail
closed without replacement approval, CommitRun, or Canon mutation. It is a
production approval-orchestration defect, not a strict Commit validator
defect. The likely repair slice is the frozen approval route/decision-state
boundary: an existing APPROVED decision whose immutable fingerprint differs
from current content must be classified as an integrity anomaly for this
operation, not silently treated as an ordinary fresh approval. No repair was
made under this FV authorization.

### Remaining gates and final status

Per the authorized stop rule, Gate 3 delayed Commit response and Gate 4
duplicate Commit replay were **not executed**. No claims are made for their
attribution or replay invariants.

The smoke/control harness completed before Gate 5 in
`.tmp/phase0d8fv-final-closure/smoke.json`. The corrected Gate 5 result changes
the final FV conclusion to:

**PARTIALLY PASSED — REPAIR REQUIRED**.

The accepted RC2 baseline remains valid, but Phase 0D8-FV cannot be declared
passed and is not ready for 0D8-SEAL. A separate production repair
authorization is required before rerunning Gate 5 and then the remaining
delayed-response and duplicate-replay gates.

### Closure validation and cleanup

- The final underscore-prefixed harness/fixture helpers compiled successfully.
- `node --check web/static/app.js` and `git diff --check` passed.
- Because the closure run changed only standalone underscore-prefixed helpers
  and evidence controls, no collected production/test implementation changed;
  the full suite was nevertheless rerun after the helper update:
  **2483 passed, 0 failed, 0 skipped**, 2 pre-existing unknown-mark warnings.
- Final app.js SHA256 remained
  `0096CCD034D0E55F87595A112EF8C0FB480CBEBC95471F0EF688C6C557AEF33C`; app.js
  was not changed in this resume.
- Owned Edge processes: `0`; fixture Python servers: `0`; temporary Edge
  profiles: `0`; fixture ports `7867/7868`: free.

## Phase 0D8-FV delayed Commit / replay closure attempt

### Replay-identity preflight

The real visible approve request body contains only `force` and `polish`; it
does not carry a client-generated operation ID. The actual replay identity is
server-derived by `ChapterCommitService` from project, chapter, source hash,
and source version, persisted as `CommitRun.commit_id`, and returned in the
successful approve response. Gate 4 was therefore allowed to use the
persisted `commit_id` as the recovered server operation identity, without
fabricating an ID or calling a lower-level service.

### Gate 3 delayed Commit — VERIFICATION INCOMPLETE / STOP

Evidence: `.tmp/phase0d8fv-delay-replay/gate3-delayed-commit.json`.

The accepted barrier was Model B: the real `POST /api/review/approve` no-polish
operation completed CommitRun and Canon persistence, while the tests-only
middleware held the HTTP response after `call_next` and before returning it to
the browser. The sequence was:

```text
visible Y Commit
→ CommitRun/Canon durable for Y
→ response held
→ visible select Z
→ selected/review-version/preview converge on Z
→ response released
```

Durable results were correct:

- Commit ID: `c80b6d03e67ff7aa`.
- Commit source: `manual_v006` / Y.
- Canon revision: `canon-chapter-001-v001` / Y.
- Y fingerprint: `017b2a88ba37d8bf0683d390bfa3ab85c34f7468c5a99fe00769a82fb0730a47`.
- Y approval decision ID was identical in CommitRun and Canon provenance.
- Counts: exactly one CommitRun and one Canon revision.
- No POST occurred after Z selection except the authorized
  `POST /api/versions/select`.

The visible identity convergence was partial. After release, selected pointer,
preview, and review-version were Z (`manual_v007`), and exact transition state
was `Human decision: STALE`; however the legacy chapter-level
`review-status` still displayed `当前审核状态：approved`. The completion log
also said only `审核通过，章节已提交` without identifying Y. This is not safe
to interpret as Z remaining visibly unapproved or as an unambiguous Y
attribution. Per the authorization, Gate 3 is marked **INCOMPLETE**, not
guessed as PASS.

This reproduces a production projection/attribution defect at the frozen
legacy review boundary. No production repair was made. The required repair
slice is a targeted exact-version review projection/notification correction;
it must preserve RC1 selection ownership and RC2/RC3 authority guards.

### Gate 4 duplicate replay

**NOT EXECUTED.** Gate 4 was stopped after the Gate 3 visible attribution
defect, as required by the production-freeze and stop rules. No replay or
duplicate-cardinality claim is made.

### Closure conclusion

The delayed operation proved durable Y provenance and no retargeted Commit, but
the visible legacy `approved` projection and generic completion message leave
Z attribution ambiguous. Final status is:

**PARTIALLY PASSED — FURTHER REPAIR REQUIRED**.

Focused/expanded/full RC3 baselines remain authoritative because this
continuation changed only standalone underscore-prefixed runners and evidence
controls: 53 focused, 133 expanded, and 2484 full-suite passed. Edge profiles,
fixture servers, temporary projects, and ports were cleaned. Phase 0D8-SEAL
was not entered.

## Phase 0D8-FV-RC3 same-version fingerprint drift closure

RC3 repaired the remaining approval-orchestration defect. Before the repair,
same Version Y had an APPROVED H1 decision while its authoritative content had
drifted to H2; the normal approve-and-Commit operation minted replacement H2
authority and produced one CommitRun and one Canon revision. The corrected
tests-only fixture and pre-fix evidence are retained under
`.tmp/phase0d8fv-final-closure/`.

The production repair in `web/routes.py` now inspects exact-version decision
history before `update_review_status`. If the same project/timeline/branch/
chapter/source/version has a historical fingerprint different from the current
authoritative fingerprint, it returns `APPROVAL_FINGERPRINT_MISMATCH` with safe
H1/H2 and decision metadata. It does not create a replacement decision, alter
lineage or selection, enter optional-polish handling, or reach Commit. Distinct
version STALE/MISSING lifecycle remains valid.

RC3 evidence:
`.tmp/phase0d8fv-rc3-fingerprint/gate5-fingerprint-mismatch.json`,
`.tmp/phase0d8fv-rc3-fingerprint/distinct-version-control.json`, and the
RC2 anomaly regression files in the same directory. Fingerprint drift produced
zero decision, CommitRun, and Canon deltas; distinct-version control produced
one valid approval, one CommitRun, and one Canon revision with matching
provenance.

## Phase 0D8-FV-RC4 exact-version projection and attribution closure

RC4 repaired the authorized Gate 3 production defect in the browser projection: the legacy review status is now owned by the active exact-version state, and the approval/commit notification names the frozen trusted source version. Production changes were limited to `web/static/app.js` and the `app.js?v=13` cache-buster in `web/templates/index.html`; no backend authority or lineage path changed.

Fresh Edge evidence is retained at `.tmp/phase0d8fv-rc4-projection/gate3-delayed-commit.json`. The harness held the response after durable Y completion, selected Z before release, and verified both during and after release: selected/review/preview were Z, exact visible review state was `STALE`, Z was not approved or committed, and the notification identified Y as `manual_v006`. Durable state contained exactly one Y CommitRun and one Y Canon revision with matching provenance. The normal current-Y control is `.tmp/phase0d8fv-rc4-projection/normal-current-y.json`.

RC4 validation: focused **57 passed**, expanded **137 passed**, and full suite **2488 passed, 0 failed, 0 skipped**, with two pre-existing unknown-mark warnings. Static checks, asset cache-buster verification, and harness cleanup passed. Gate 4 duplicate replay remains **NOT EXECUTED** by authorization; no SEAL, commit, push, PR, or remote mutation occurred.

RC4 is **PASS - READY TO RESUME REMAINING PHASE 0D8-FV GATES**, subject to a separate owner authorization before Gate 4. Phase 0D8-SEAL remains unopened.

## Phase 0D8-FV Gate 4 duplicate strict Commit replay closure

Date: 2026-08-01. Execution configuration: single agent, fresh Microsoft Edge
temporary profile, loopback CDP, cache-disabled browser, isolated fixture
project, real FastAPI routes and real visible approval/strict Commit flow. No
production code was changed during Gate 4; the accepted RC4 production freeze
remains intact.

Evidence: `.tmp/phase0d8fv-gate4-replay/gate4-duplicate-replay.json`.

The first visible flow issued `POST /api/review/approve` with
`{"force":false,"polish":null}`, then the visible optional-polish path issued
the strict Commit-capable request `{"force":true,"polish":false}`. The fixture
held the successful response after durable completion. The replay resent the
same endpoint and method with the byte-equivalent strict request body; it did
not add an operation ID or alter authority context. Actual request-ledger
comparison was: first body == replay body (`true`).

The server-derived operation identity was `90a7e56a04eb0524` for both first and
replay. Durable cardinality stayed exactly one CommitRun and one Canon revision;
CommitRun `canon_revision_id` stayed `canon-chapter-001-v001`. First and final
approval provenance were equal across project, timeline, branch, chapter,
source type/version, fingerprint, decision ID, decision type/status, decision
timestamps, and validation timestamp. The first and replay requests passed
through `validate_approved_commit`; the replay created no replacement approval
(decision count remained 2), and no legacy fallback audit entry appeared.

Secondary authoritative mutation audit found no second CommitRun, Canon
revision, chapter projection, archive mutation, or duplicated provenance. The
two `commit_chapter` and four validation audit observations represent the first
and replay transport/path calls; persisted authoritative state remained
idempotent. The replay HTTP response was 200 and referenced the same durable
Commit ID and Canon revision. The browser remained on `manual_v006` with exact
approved state and RC4 attribution `提交完成：manual_v006（第 1 章）`; no second
visible UI action, retargeting, approval, or Commit POST occurred.

Regression decision: the accepted RC4 focused (57), expanded (137), and full
(2488 passed, 0 failed, 0 skipped) results remain authoritative because Gate 4
changed only standalone underscore-prefixed runner/evidence behavior and added
no collected test or imported production helper. Python compilation,
`node --check`, and `git diff --check` passed. Served `/static/app.js?v=13`
returned status 200 and its SHA-256 exactly matched disk:
`DA9F4E93568D0B2D31CD4A5A89DD2E2F57A80B81C8140CAA72CF50C81ECD550A`.

Production-freeze audit: no Gate 4 production edit; pre-existing RC1-RC4
working-tree changes were preserved. Cleanup ledger: owned fixture processes 0,
temporary Edge profiles 0, temporary fixture projects 0, listeners on ports
7867/7868 0. No Git commit, push, PR, remote mutation, or SEAL action occurred.

Historical Phase 0D8-FV conclusion at the pre-SEAL boundary: **PASSED - READY
FOR PHASE 0D8-SEAL AUTHORIZATION**. The current SEAL conclusion is recorded at
the top of this report and in `PHASE_0D8_SEAL_REPORT.md`.

Final RC3 validation: focused **53 passed**, expanded **133 passed**, and full
suite **2484 passed, 0 failed, 0 skipped** with two pre-existing unknown-mark
warnings. Static checks and cleanup passed. Gate 3 delayed Commit and Gate 4
duplicate replay remain intentionally unexecuted; RC3 is **PASS — READY TO
RESUME REMAINING PHASE 0D8-FV GATES**, but Phase 0D8-SEAL was not entered.
