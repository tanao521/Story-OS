# Browser QA Evidence — Phase 0D3B1-RC2E

## Session

- Observation date: 2026-07-22 (Asia/Shanghai)
- Browser: Microsoft Edge with the ChatGPT extension bridge; exact Edge version was not exposed by the bridge
- Story OS: `http://127.0.0.1:4181/` — HTTP 200
- QA harness: `http://127.0.0.1:4182/docs/design/qa/simulator-panel-review-production/harness.html` — HTTP 200
- Project context: safe server-provided `legacy-root-project`; no absolute path recorded
- Evidence directory: `docs/design/qa/simulator-panel-review-production/screenshots/`

## Console

The connected browser tab was run through each required scenario. `tab.dev.logs({levels:["error","warning","warn"]})` returned an empty list for every scenario; no unhandled rejection or page resource failure was observed.

| Scenario | Errors | Warnings | Unhandled rejections | Resource failures |
|---|---:|---:|---:|---:|
| Traditional default | 0 | 0 | 0 | 0 |
| Real automatic (`source_missing`) | 0 | 0 | 0 | 0 |
| Explicit 404 | 0 | 0 | 0 | 0 |
| QA ready | 0 | 0 | 0 | 0 |
| QA stale | 0 | 0 | 0 | 0 |
| QA source-missing | 0 | 0 | 0 | 0 |

The browser bridge emitted an unrelated ChatGPT-extension Statsig networking message outside the localhost Story OS page; it is not a Story OS console error or page resource failure.

## Network

Network acceptance was completed manually by the user in the connected browser session. The bridge does not expose a Network-panel/HAR export, so the audit record combines that manual observation with direct HTTP and source isolation checks:

- Traditional mode: no Review request and no fixture request observed; no write request.
- Automatic mode: Review GET returned HTTP 200 with `source_missing`; no POST/PUT/PATCH/DELETE path exists in the production renderer.
- Explicit 404: explicit Review GET returned HTTP 404 `PANEL_RUN_NOT_FOUND`; the rendered state retained `panel_execution_id=missing-demo` and did not fall back to an automatic result.
- QA harness: fixture reads occur on the harness origin only; the harness does not call the real Review API and emits no write requests.
- Production fixture fallback scan: NONE. Production write endpoint scan: NONE.

## Screenshot artifacts

All seven required files are valid PNGs with the following captured dimensions:

| File | Dimensions | State |
|---|---:|---|
| `production-traditional-default.png` | 2040×1020 | production default traditional mode |
| `production-real-api-state.png` | 390×843 | real API `source_missing` |
| `production-explicit-404.png` | 2040×1020 | explicit `PANEL_RUN_NOT_FOUND` |
| `production-ready-1440x900.png` | 1425×891 | QA `ready-current` |
| `production-partial-1280x800.png` | 1265×791 | QA `partial` |
| `production-stale-768x1024.png` | 753×1004 | QA `stale-mixed` |
| `production-source-missing-390x844.png` | 375×811 | QA `source-missing` |

The screenshots were captured from the production renderer or the clearly isolated QA-only harness. No absolute filesystem path, secret, or local username is present.

## Automated corroboration

- 0D3B1/0D2B3 focused checks: 11 passed.
- Web/route/static regression: 48 passed.
- `node --check`: passed.
- `python -m compileall -q .`: passed.
- Chroma: 6/6; authority assets: 16/16; Obsidian bindings: 30; real model/panel run JSON: 0/0.

## RC3 correction note

The RC3 inspection found the Harness desktop collapse was caused by the production three-column `.dashboard-layout` being reused with only one Harness child; the renderer was confined to the 224px first column. The Harness now overrides this to a single `minmax(0, 1fr)` column with `width: 100%` and `min-width: 0`. Renderer field mapping now reads fixture `panel_status`, `selected_panel_run.execution_id`, ordered persona ids from persona reviews, and string-or-list model feedback.

The browser bridge was finalized after the RC2E capture and could not be reconnected for post-fix visual screenshots. The three desktop PNGs listed above remain pre-RC3 evidence and must be recaptured before sealing.
