# Phase 0D3A2-RC2 Delivery Report

## Stage conclusion

**PASSED.** The isolated simulator review prototype now has a non-overlapping tablet flow and readable mobile authority metrics. This report supersedes the invalid responsive conclusion in the RC1 report; RC1 screenshots were manually found to contain the two defects corrected here.

## Root cause and exact fix

The root cause was CSS containment, not fixture data: at 768px the existing `@media(max-width:1100px)` rule retained `grid-template-columns:minmax(0,1fr) 250px`, leaving the primary column about 205px wide. Nested grid items had no `min-width:0`, so their min-content widths overflowed into the audit rail. At 390px the mobile authority tracks were `1fr 1fr` with auto minimums, so the raw `source_missing` value expanded one track and squeezed `未提供`.

Changed selectors and breakpoints:

- Global child containment: `.review-grid>*`, `.authority-content>*`, `.persona-grid>*`, `.lower-grid>*`, `.audit-column>*`, `.topbar>*`, `.top-actions>*` → `min-width:0`.
- Metric containment: `.metric`, `.metric strong`; `[data-metric="panel-status"] strong` receives a readable wrapping policy.
- Long audit values: `.selection-card dd` and `.audit-row strong` use `overflow-wrap:anywhere`.
- `@media(max-width:900px)`: `.review-grid` becomes one column; persona and lower grids become one column; audit cards become a vertical grid with no residual margins.
- `@media(max-width:760px)`: controls stack; authority tracks become `minmax(0,1fr) minmax(0,1fr)`.

No fixed height/width, absolute/sticky positioning, negative margin, or min-width constraint was added. The prior fixed audit column is retained only above 900px, where it is intentional desktop structure.

The prototype JS keeps fixture/API values unchanged and maps only the display label `source_missing` → `来源缺失`; `未提供` is rendered with `white-space:nowrap` so it remains horizontal.

## Server and browser evidence

- Server: repo-root `py -m http.server 4180 --bind 127.0.0.1`, listener `127.0.0.1:4180`, HTTP 200 for the prototype URL.
- URL: `http://127.0.0.1:4180/docs/design/prototypes/simulator-panel-review/`.
- Four fresh browser captures were regenerated after the final JS initialization cleanup. Browser capture dimensions include the scrollbar gutter:
  - `ready-1440x900.png`: PNG 1425×891
  - `partial-1280x800.png`: PNG 1265×791
  - `stale-768x1024.png`: PNG 753×1004
  - `source-missing-390x844.png`: PNG 375×811

## Geometry results

The check used `getBoundingClientRect()` for the authoritative panel, signal cards, selection trace, audit ledger, evidence, usage/staleness, and warnings. Nested persona cards were treated as intended parent/child content and excluded from the sibling-overlap assertion.

- 768×1024 `stale-mixed`: `review-grid` and audit children all use the full 473.4px content track; primary flow ends at y=976.2 and selection trace starts at y=994.2. Unintended sibling overlaps: **0**. `scrollWidth=753`, `innerWidth=768`.
- 390×844 `source-missing`: authority panel is x=16..359.2; selection trace starts after the primary flow at y=1323.7. Unintended sibling overlaps: **0**. `RETENTION RISK` value is `未提供` in a 151.5px cell with `white-space:nowrap`; `PANEL STATUS` is `来源缺失`. `scrollWidth=375`, `innerWidth=390`.
- Desktop/compact geometry was also checked at 1440×900 and 1280×800; only intended persona-grid parent/child intersections were reported.

## Console and state coverage

Final browser console logs: **empty** (`[]`). The required representative states were exercised: `ready-current`, `partial`, `stale-mixed`, `source-missing`, `not-run`, `failed`, `explicit-run-404`, `usage-null`, `agreements-conflicts`, and `warnings-multiple`. The 404 state retained safe context; usage null remained `未提供`; agreement/conflict semantics and `unresolved` remained visible.

## Regression, protection, and isolation

- `52 passed` for the Phase 0D2B3 + web/route/static regression selection.
- `python -m compileall -q .`: exit 0.
- `node --check docs/design/prototypes/simulator-panel-review/prototype.js`: exit 0.
- Forbidden-reference/external-endpoint scan for the prototype: clean.
- `protected_ok=True`; Chroma=6, authority assets=16, Obsidian bindings=30; model/panel run JSON counts=0/0.
- Only allowed prototype/spec/report paths were changed or added. Existing unrelated dirty-worktree changes were preserved and not attributed to RC2.

## Closure and hand-off

0D3A2 may be formally closed after RC2. **Do not enter Phase 0D3B in this task.** No commit, push, reset, clean, rebase, production change, backend change, real model/panel run, Chroma/Obsidian mutation, or story write was performed.
