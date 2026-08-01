# Story OS — Phase 0D8-FV-BH1 Delivery Report

## Final conclusion

**PASS — browser harness stabilized through the repository-supported local Edge/CDP fallback.**

The in-app Browser was not stable: two bounded attempts reproduced an
auditable layout failure at the first interaction boundary. The repository
already contained an Edge/CDP test pattern and the installed local Edge was
available, so BH1 continued through that supported fallback without adding a
dependency or changing production code.

Three fresh, independent Edge profiles completed one real visible version
action each. The action produced the expected `GET /api/versions/content`
request with HTTP 200 and a non-empty final `#text-preview` DOM. The product
URL and title stayed stable, no abnormal data-page state occurred in the CDP
fallback, the served JavaScript matched disk, and cleanup completed.

This PASS authorizes return to the remaining **0D8-FV** scenarios only. It does
not authorize 0D8-SEAL, roadmap changes, production repair, commit, push, PR,
Provider calls, or memory/Canon changes.

## Authorization and scope

- Scope: Phase 0D8-FV-BH1 only.
- Execution: one agent, medium effort, tests-only harness changes.
- No production files were edited.
- No approvals, revisions, selection mutations, Commit, Canon, Provider, or
  external credentials were used.
- Historical `.tmp/phase0d8fv-harness` evidence was preserved and not
  overwritten.

## Environment inventory

| Item | Observed value |
|---|---|
| OS | Windows 11 build 26200 |
| Python | 3.14.5 via `uv` |
| Node | v24.14.0 |
| npm | 11.9.0 |
| pytest | 9.1.1 via `uv` |
| Fixture URL | `http://127.0.0.1:7868/` |
| Browser fallback | Microsoft Edge `150.0.4078.105` |
| Browser executable | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| Browser profile | fresh temporary profile per run |
| CDP | loopback endpoint, fresh port per run |
| Cache | disabled and browser cache cleared where supported |
| In-app Browser executable/profile/CDP | not exposed by the surface |

Runtime, ports, and starting worktree evidence are retained in
`.tmp/phase0d8fv-bh1/runtime.txt`, `ports-before.txt`, `status-before.txt`, and
`diff-before.txt`.

## Browser surfaces evaluated

### In-app Browser

The product loaded with title `Story OS Web Console`, URL
`http://127.0.0.1:7868/`, one `#manual-list`, and three manual versions. The
exact action selector was:

`#manual-list button[onclick*="loadVersionContent"]`

The target was present in DOM but had a `0×0` rectangle, `offsetParent=false`,
and zero-size ancestors through `#versions-panel`. A DOM-CUA click on the
visible `#versions-panel` navigation anchor left the product URL unchanged and
again produced the abnormal `data:image` screenshot/page state. This was
reproduced after fresh navigation and bounded interaction attempts. Evidence
is retained in `.tmp/phase0d8fv-bh1/` and the browser session was finalized.

### Local Edge/CDP fallback

The repository-supported CDP pattern was `tests/_phase0d6c_rc13_fv1_e1_cdp.py`
using the already-installed `websocket` package. BH1 added a narrowly scoped
version-action runner, `tests/_phase0d8fv_bh1_cdp.py`, and used a 1280×720
window to remove the default headless viewport ambiguity.

## Minimal fixture

`tests/_phase0d8fv_bh1_fixture_server.py` created a fresh temporary project
with only three manual versions (`manual_v001`–`manual_v003`), real Story OS
routes/assets, and a JSONL request audit middleware. It did not seed approval,
revision, or Commit state and exposed no control endpoint to the product tab.

The final request summary records six content reads across the two fallback
rounds, all HTTP 200, no non-GET requests, and no forbidden mutation path:
`.tmp/phase0d8fv-bh1/request-summary.json`.

## Selector, geometry, and interaction evidence

The fallback performed the BH1 ladder in order:

1. DOM presence: three exact version action buttons.
2. Geometry: after real navigation, the target was visible; representative
   pre-scroll geometry was `x=1003, y≈832–859, w=44, h=30`.
3. Deterministic scroll: CDP `DOM.scrollIntoViewIfNeeded` moved the target to
   a hit point near `(1025, 290)`.
4. Hit-test: `BUTTON`, its action container, article, `#manual-list`, and the
   containing section were returned by `elementsFromPoint`.
5. One visible click: the exact `loadVersionContent('manual', 1)` control was
   clicked by mouse coordinates.
6. Final DOM/network: `#text-preview` was non-empty and the request log showed
   `/api/versions/content?source_type=manual&version=1` with status 200.

The exact per-run records are:

- `.tmp/phase0d8fv-bh1/cdp-final-run-1.log`
- `.tmp/phase0d8fv-bh1/cdp-final-run-2.log`
- `.tmp/phase0d8fv-bh1/cdp-final-run-3.log`

## Three fresh smoke runs

| Run | Fresh profile | Visible target | Hit-test | Expected request | Final DOM | Product tab |
|---|---:|---:|---:|---:|---:|---:|
| 1 | PASS | PASS | PASS | 200 | non-empty `#text-preview` | stable |
| 2 | PASS | PASS | PASS | 200 | non-empty `#text-preview` | stable |
| 3 | PASS | PASS | PASS | 200 | non-empty `#text-preview` | stable |

The final DOM retained `Story OS Web Console`, the same product URL, a visible
preview panel, `manual_v001` metadata, and the expected prose content. No
abnormal data-page state appeared in these fallback runs.

## Asset identity and product/control isolation

- Disk and served `web/static/app.js?v=12` SHA256 matched:
  `b1c1ad82b2c85439a6a68edec08a6d401c1f881b689561acdec3626c29c3ff9f`.
- Asset evidence: `.tmp/phase0d8fv-bh1/asset-sha.json`.
- Control operations were performed by the local CDP runner and shell evidence
  channel; the product tab navigated only to the fixture root and its own real
  routes.
- The fixture server was stopped after the runs; the product tab was closed
  and the in-app Browser session finalized.

## Regression and static validation

- `uv run python -m py_compile tests/_phase0d8fv_bh1_fixture_server.py tests/_phase0d8fv_bh1_cdp.py`: **PASS**.
- `git diff --check`: **PASS**; only pre-existing LF/CRLF warnings were emitted.
- Relevant fixture smoke: **3/3 PASS** in the final CDP round.
- Full suite: **not rerun for BH1**. The new helpers are tests-only underscore
  helpers and are not collected/imported by the normal pytest suite; the prior
  exact full-suite result remains historical evidence in
  `.tmp/phase0d8fv-harness/`.

Validation evidence is in `.tmp/phase0d8fv-bh1/validation-summary.json` and
`diff-check.log`.

## Production audit

Production diff introduced by BH1: **0 files**.

BH1-owned source changes are limited to the new tests-only fixture and CDP
helper plus this report and retained evidence under `.tmp/phase0d8fv-bh1/`.
The already-dirty production files and historical 0D8 files listed by the
starting worktree audit were not reclassified or overwritten.

## Cleanup

- Three Edge processes/profiles were stopped and removed.
- In-app Browser tab/session was closed/finalized.
- Fixture server process was stopped and port 7868 was verified free.
- The exact temporary fixture project under
  `%TEMP%\phase0d8fv_bh1_*` was removed after containment verification.
- No historical `.tmp/phase0d8fv-harness` evidence was deleted.

Cleanup evidence: `.tmp/phase0d8fv-bh1/cleanup-summary.json`.

## Retained evidence

All BH1 evidence is under `.tmp/phase0d8fv-bh1/`, including runtime and
worktree inventory, in-app diagnosis, CDP run logs, request summary, asset
hashes, validation, and cleanup records. Historical evidence remains under
`.tmp/phase0d8fv-harness/`.

## Recommendation

BH1 is complete and the browser execution gate is cleared for the remaining
authorized 0D8-FV visible drift/race/replay scenarios. Before any later
0D8-SEAL consideration, those scenarios must still be executed under their
separate authorization and reported independently.
