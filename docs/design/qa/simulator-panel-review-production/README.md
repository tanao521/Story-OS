# 0D3B1 production renderer QA harness

QA-only fallback used when the in-app browser route-interception runtime is unavailable. It loads the real production `simulator-panel-review.js` and `.css`; it does not duplicate or get referenced by the production template. The selector exposes eleven redacted review fixtures from `docs/design/fixtures/model_persona_panel_review/`.

Serve the repository root with a static server, then open `docs/design/qa/simulator-panel-review-production/harness.html`. This harness does not call the Story OS API and does not write project data.
