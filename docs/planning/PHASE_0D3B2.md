# Phase 0D3B2 — Simulator Context Navigator & Saved Run Explorer

## Status

**IMPLEMENTED — PASSED**

Phase 0D3B1 is sealed under the owner-accepted visual evidence limitation in [PHASE_0D3B1_FINAL_SEAL.md](PHASE_0D3B1_FINAL_SEAL.md). This phase adds a read-only context navigator and saved Panel Run explorer to the existing production Simulator / Panel Review surface.

## Scope and decisions

- Reused `/api/projects`, `/api/projects/active`, the existing Review GET routes, `storyosApiGet`, URLSearchParams, `pushState`, `popstate`, and the existing production renderer.
- Added one narrowly scoped GET aggregation endpoint: `/api/simulator/context`.
- The endpoint returns only safe metadata: project display identity, timeline metadata, chapter numbers/titles, source-version metadata, and saved Panel Run metadata. It never returns chapter prose, prompt, secret, provider endpoint, absolute path, or raw exception.
- No POST/PUT/PATCH/DELETE, model/provider call, Run creation, rerun, repair, story write, Chroma mutation, or Obsidian mutation was added.

## Context behavior

- No valid project: the navigator shows a safe empty state and skips timeline/chapter/source/run requests.
- One valid project: the safe server-provided project id is selected without inventing an id.
- Multiple projects: the user must choose; no guessing is performed.
- Timeline is scoped to the selected project and currently exposes the existing `main` timeline metadata.
- Chapters are discovered only within the selected project and are scoped to the selected timeline.
- Source versions are metadata-only and become selectable only when the data model provides a real safe source-version id.
- Saved Panel Runs are scoped to project + timeline + chapter and expose status, staleness, usage completeness, and ordered Persona ids.
- Automatic selection removes `panel_execution_id`; explicit selection writes it into the safe URL and uses the existing explicit GET route. A missing explicit run remains `PANEL_RUN_NOT_FOUND` with no fallback.
- Parent changes abort in-flight context loading and increment a request generation so stale responses cannot overwrite a newer selection.

## Files

- `story-os-demo/web/routes.py`
- `story-os-demo/web/templates/index.html`
- `story-os-demo/web/static/simulator-context-navigator.js`
- `story-os-demo/web/static/simulator-panel-review.css`
- `story-os-demo/tests/test_web_routes.py`
- `story-os-demo/tests/test_phase0d3b1_simulator_panel_frontend.py`

## Acceptance

All focused and route/static regression tests passed. The browser bridge was not used as a phase gate, consistent with the owner decision recorded in the 0D3B1 Final Seal.
