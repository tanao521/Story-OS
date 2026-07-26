# Phase 0D3A1 — Simulator Front-End Readiness Audit

## Scope and gate

This phase is an audit and design-input package only. Phase 0D2B3 is recorded as PASSED and sealed in `story-os-demo/docs/planning/PHASE_0D2B3_DELIVERY_REPORT.md`. Its read-only `ModelPersonaPanelReview` contract and the two GET routes are present. No production page, backend contract, run, model call, or data write is performed here.

## Evidence baseline

- Application root: `story-os-demo/`.
- Server: FastAPI in `story-os-demo/web/app.py`; Jinja2 serves `web/templates/index.html`; `/static` mounts `web/static`.
- Client: one server-rendered HTML shell plus vanilla JavaScript modules and CSS; no package manifest, bundler, TypeScript config, component library, or icon package was found. `requirements.txt` defines pytest and the Python Web stack.
- Review routes: `GET /api/reader-persona/model-panel/review` and `GET /api/reader-persona/model-panel/runs/{panel_execution_id}/review` in `story-os-demo/web/routes.py`.
- Review contract: `story-os-demo/core/contracts/model_persona_panel_review.py`; service and focused tests are the 0D2B3 implementation.
- Current real run directories contain no JSON; design therefore uses documentation-only fixtures.

## Decision

The current architecture is ready for a first simulator view without a new application. Use the existing shell and a URL-addressable simulator section; preserve project/timeline/chapter context in query parameters. The field mapping, state matrix, fixture schema, and design brief are in the companion documents. Stop at 0D3A1; 0D3A2 may begin only after this package is accepted.
