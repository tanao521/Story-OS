# Story OS — Phase 0D8-FV-RC1 Delivery Report

Date: 2026-08-01  
Scope: selection identity convergence and stale preview invalidation only  
Acceptance browser: fresh Microsoft Edge/CDP, loopback fixture, isolated profile

## Final conclusion

**PASSED — READY TO RESUME REMAINING PHASE 0D8-FV GATES**

RC1 repairs the reproduced Gate 2 defect. A visible selection now follows the
preferred contract: selection, active review target and preview identity
converge on the selected version. The repaired behavior does not approve,
request changes, Commit, write Canon, or mutate decision/transition/evidence
authority.

RC1 does not authorize 0D8-SEAL and does not execute Gate 5, Gate 3 or Gate 4.

## Pre-fix defect and root cause

The reproduced sequence was:

```text
open Y → select Z
selected pointer = Z
review target = Z
preview identity/content = Y
```

The root cause was in the derived frontend display path. `selectVersion()`
only posted `/api/versions/select` and called `refreshAll()`. It did not call
`loadVersionContent()` for the newly selected identity, clear the existing
preview, or invalidate the active preview ownership key. `refreshAll()` refreshes
status and version lists but intentionally does not replace the active preview.
The existing guard protected review/evidence responses after a content load,
but there was no new Z content load and the quality/continuity paths were not
bound to the same preview request ownership.

## RC1 repair

Production change: `web/static/app.js` only.

- Selection now uses the deterministic contract “select Z → actively view Z”.
- The successful selection transition increments a selection epoch, sets the
  exact selected identity, clears old preview text/metadata/cards, and starts
  the real Z content route.
- Preview loading has explicit loading and unavailable states; failed Z loads
  never retain Y content as fallback.
- Existing review/evidence ownership is extended with project, timeline, branch,
  chapter, source type and version scope; content, quality, continuity,
  decision and assembly-evidence responses must still own the active view before
  rendering.
- Delayed old responses cannot restore old preview content after selection.
- The selection path contains no approval, Commit, archive, Canon, decision or
  transition mutation.

The preferred selected/review/preview identity contract is now explicit:

```text
selected pointer = review target = preview identity = selected version
```

## Edge/CDP acceptance

Evidence: `.tmp/phase0d8fv-rc1-selection/selection-delayed-y.json` and the
adjacent `selection-delayed-y.png` screenshot.

Fresh fixture sequence:

```text
open Y
hold Y content response
select Z through the real visible select action
settle Z content and review state
release delayed Y content response
```

Observed before release:

```text
selected = manual_v007
preview = manual_v007
review target = manual_v007
text = Version Z ...
```

Observed after releasing the delayed Y response: the final DOM remained exact
Z for selected pointer, preview metadata, preview content, review target and
transition state. No stale Y response overwrote Z. Mutation counts were:

```text
Commit runs = 0
Canon revisions = 0
```

The selection POST was captured as
`POST /api/versions/select {"source_type":"manual","version":7}`. The
request/response ledger and final DOM are retained in the RC1 evidence file.

## Deterministic tests and regression

- RC1 selection contract plus existing frontend isolation tests: **10 passed**.
- RC1 plus existing 0D8 focused matrix: **50 passed**.
- Expanded related matrix: **163 passed**.
- Full suite: **2479 passed, 0 failed, 0 skipped**, normal pytest exit, two
  pre-existing unknown-mark warnings. The historical 2471 count increased by
  the eight newly added RC1 tests.
- Collection: **2479 tests collected**, 0 collection errors.
- `node --check web/static/app.js`: passed.
- Python compilation for changed helpers: passed.
- `git diff --check`: passed with only pre-existing line-ending warnings.

The first post-change expanded run exposed one stale static assertion tied to
the old local variable spelling; it was updated to assert the ownership
contract rather than the obsolete implementation spelling. The rerun passed
163/163 and the full suite passed.

## Asset and production audit

The browser-served and disk `web/static/app.js?v=12` SHA256 matched:

```text
65a30fbc163dfc571bbecb4d1ad0fbb9bbefe19dda501f0cb69e6851e5cb808b
```

The browser executed the repaired disk asset through the real fixture server.
The only production implementation file introduced by RC1 is the authorized
`web/static/app.js` repair. Existing dirty production files from prior phases
were preserved and not reclassified. No authority, Commit, Canon, Provider,
timeline, dependency or production configuration changes were made.

## Invariant closure

| Invariant | Result |
|---|---|
| selected pointer equals review target after selection | CLOSED |
| selected pointer equals preview identity after selection | CLOSED |
| old preview invalidated before new content is authoritative | CLOSED |
| delayed old success cannot overwrite active version | CLOSED by Edge/CDP |
| delayed old error cannot overwrite active version | CLOSED by ownership guard and deterministic tests |
| approval is not transferred across selection | PRESERVED; no approval mutation in RC1 |
| selection repair causes no Commit or Canon mutation | CLOSED; both counts zero |

## Cleanup and next authorized scope

Owned Edge/CDP processes, temporary profiles, fixture servers and scenario
workspaces were cleaned. Ports 7867 and 7868 were free. Prior evidence roots
`.tmp/phase0d8fv-harness`, `.tmp/phase0d8fv-bh1` and
`.tmp/phase0d8fv-final-browser` were preserved. New RC1 evidence remains under
`.tmp/phase0d8fv-rc1-selection/`.

RC1 is complete. The next work, requiring the separate remaining-FV
authorization already specified by the owner, may resume Gate 5 invalid/
conflicting authority taxonomy, Gate 3 delayed Commit response, and Gate 4
duplicate Commit replay. 0D8-SEAL remains out of scope.

## SEAL reconciliation (current state)

RC1 current result: **PASSED**. The remaining-gates language above is retained
as historical RC1-era scope; RC2, RC3, RC4, Gate 4, and Phase 0D8-SEAL were
subsequently completed under separate authorization.
