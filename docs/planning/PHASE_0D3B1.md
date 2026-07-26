# Phase 0D3B1 — Simulator Panel Review Production Integration

## Scope

Integrate the read-only Simulator / Panel Review surface into the existing FastAPI + Jinja2 + vanilla JavaScript shell. The default remains traditional writing mode. The integration reuses the existing `apiGet` request lifecycle and review endpoints; it does not add writes, model calls, provider calls, or a second application shell.

## Production integration contract

- Template seam: `story-os-demo/web/templates/index.html` adds the mode switch, the hidden simulator section, and feature CSS/JS assets.
- Request seam: `story-os-demo/web/static/app.js` exports `window.storyosApiGet` and emits `storyos:dashboard-ready`; existing `AbortController` and stale-project generation remain authoritative.
- Renderer: `story-os-demo/web/static/simulator-panel-review.js` validates `mode`, `view`, `project`, `timeline_id`, `chapter_id`, and optional `panel_execution_id`; it renders all review states with DOM APIs and `textContent`.
- Styles: `story-os-demo/web/static/simulator-panel-review.css` is feature-namespaced and keeps the RC2 responsive thresholds.
- Automatic review: `GET /api/reader-persona/model-panel/review?chapter_id=...`.
- Explicit review: `GET /api/reader-persona/model-panel/runs/{panel_execution_id}/review?chapter_id=...`; `PANEL_RUN_NOT_FOUND` is terminal and never falls back.
- Project context: the safe URL project key is compared with `GET /api/projects/active`; the review request intentionally omits `project_root` and `timeline_id` because the existing backend route does not accept those query parameters.

## State coverage

The renderer maps ready, partial, not-run, failed, stale, source-missing, invalid-context, loading, transport-error, and explicit-not-found states. Persona order is preserved; authoritative fields and model supplements are separate; agreement, conflict (`unresolved`), evidence, execution, usage, staleness, and warnings are visible.

## QA fallback

The preferred browser route-interception runtime was unavailable in this environment because the bundled browser client could not resolve `classic-level.mjs`. The QA-only fallback at `docs/design/qa/simulator-panel-review-production/` loads the real production renderer and CSS against eleven redacted fixtures; it is not referenced by production templates and performs no API writes.

## Gate

Implementation and static checks are complete. Browser screenshots and live route-interception evidence remain outstanding, so this phase must not be marked fully passed until the browser runtime is restored and the required production deep-link, popstate, traditional-mode regression, console, and screenshot checks are completed.
