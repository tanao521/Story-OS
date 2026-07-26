# Simulator component and implementation specification

| Component | Semantic DOM / inputs | Boundary and behavior | Prototype selector / future location |
|---|---|---|---|
| SimulatorModeShell | `main`, mode buttons, URL params | sibling mode, no shell copy; buttons are navigation-only | `.preview-shell` / `index.html` section |
| ReviewHeader | `header`; project/timeline/chapter/source | escaped context chips, deep-link values | `.topbar` / `app.js` module |
| ReviewStatusBanner | `section[aria-live]`; review status/warnings | distinct text/icon per enum | `#statusBanner` |
| SelectionSummary | `dl`; execution id/reason/status/staleness | explicit id never silently falls back | `#selection` |
| AuthoritativePanelSummary | `section`; `authoritative_panel` | gold rule; fixed source of scores/risk/flags | `.authority-panel` |
| PersonaReviewCard | `article`; ordered card fields | authority block first, model inset second; missing is not zero | `.persona-card` |
| Agreement/Conflict lists | `section`, list items | `≈` vs `≠`, labels and unresolved text, not color-only | `#agreementList`, `#conflictList` |
| Evidence/Execution/Usage/Staleness | `aside` sections; summary objects | counts only; null usage says 未提供; no recompute | `#evidence`, `#execution`, `#usage` |
| StructuredWarningList | `ul`; warnings | safe codes/labels, no raw exception | `#warnings` |
| Loading/Error/Empty states | live region / section replacement | loading skeleton; 404 retains context; no write controls | status + `.empty` |

Production flow: parse URL → select `/review` for chapter or `/runs/{id}/review` for explicit id → call existing `apiGet` with project context → abort stale requests using existing `storyosRequestGeneration` → render banner → authority → ordered cards → signals → audit. Use `textContent`/escaping, never unsafe `innerHTML` for contract text. A 404 is an error container, not a fallback selection.
Responsive implementation note (RC2): at <=900px the review and audit regions are a single vertical flow; at <=760px controls and authority metrics use min-width-safe tracks. Status enums remain fixture/API values, but `source_missing` is rendered as the readable UI label `来源缺失`.
