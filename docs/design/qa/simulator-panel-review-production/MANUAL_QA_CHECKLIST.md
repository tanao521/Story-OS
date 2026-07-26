# Phase 0D3B1-RC2 Manual QA Checklist

Status values: `PASS`, `FAIL`, or `NOT APPLICABLE`.

## Session

- Date/time: 2026-07-22
- Browser and version: Microsoft Edge with ChatGPT extension bridge; exact version not exposed
- Story OS URL: `http://127.0.0.1:4181/`
- QA harness URL: `http://127.0.0.1:4182/docs/design/qa/simulator-panel-review-production/harness.html`
- Project context: server-listed valid legacy project `legacy-root-project`; Review identity remains `default-project/main`
- Human evidence: user stated “人工验收完成”; one visible QA ready-state screenshot was supplied in chat
- Screenshot directory: `docs/design/qa/simulator-panel-review-production/screenshots/` (seven valid PNGs)

## Production default and context

| Check | Result | Evidence / notes |
|---|---|---|
| `/` defaults to traditional writing | PASS | User-confirmed manual acceptance; no saved screenshot. |
| Existing navigation works | PASS | User-confirmed manual acceptance. |
| Simulator is not active by default | PASS | User-confirmed manual acceptance. |
| No visible page error | PASS | User-confirmed manual acceptance; no Console transcript supplied. |
| Existing real project context used | PASS | `/api/projects` exposes one valid legacy project; frontend now reuses its server-provided safe id. |
| `production-traditional-default.png` captured | PASS | Valid PNG, 2040×1020; production default traditional mode. |

## Production Review states

| Check | Result | Evidence / notes |
|---|---|---|
| Automatic Review state observed from real API | PASS | Real GET returned HTTP 200 and `source_missing`; user confirmed manual acceptance. |
| `production-real-api-state.png` captured | PASS | Valid PNG, 390×843; real API `source_missing` state. |
| Explicit missing run shows `PANEL_RUN_NOT_FOUND` | PASS | Real GET returned HTTP 404; user-confirmed manual acceptance. |
| Explicit URL context and execution id remain intact | PASS | User-confirmed manual acceptance. |
| Explicit 404 does not request automatic fallback | PASS | User-confirmed Network acceptance; no HAR export supplied. |
| `production-explicit-404.png` captured | PASS | Valid PNG, 2040×1020; `PANEL_RUN_NOT_FOUND` with explicit id retained. |

## QA harness viewports

| Fixture / viewport | Result | Screenshot / notes |
|---|---|---|
| ready-current / 1440x900 | PASS | Harness visibly rendered; user confirmed QA acceptance. |
| partial / 1280x800 | PASS | User-confirmed manual acceptance; no saved file. |
| stale-mixed / 768x1024 | PASS | User-confirmed manual acceptance; no saved file. |
| source-missing / 390x844 | PASS | User-confirmed manual acceptance; no saved file. |
| `production-ready-1440x900.png` | PASS | Valid PNG, 1425×891; isolated QA `ready-current`. |
| `production-partial-1280x800.png` | PASS | Valid PNG, 1265×791; isolated QA `partial`. |
| `production-stale-768x1024.png` | PASS | Valid PNG, 753×1004; isolated QA `stale-mixed`. |
| `production-source-missing-390x844.png` | PASS | Valid PNG, 375×811; isolated QA `source-missing`. |

Quick fixture sweep (ready-cached / not-run / failed / agreements-conflicts / usage-null / warnings-multiple / explicit-run-404): **PASS by user attestation; no per-state screenshots or transcript supplied.**

## Console and Network

| Check | Result | Evidence / notes |
|---|---|---|
| Console project errors = 0 | PASS | Connected browser logs were empty for all six required scenarios. |
| No unhandled rejection | PASS | No unhandled rejection observed in connected browser session. |
| No fixture 404 in production | PASS | Production fixture scan is NONE; user-confirmed acceptance. |
| No external resource failure | PASS | User-confirmed acceptance; static scan found no external URL. |
| Traditional mode sends no Review request | PASS | User-confirmed Network acceptance. |
| Automatic sends only automatic Review GET | PASS | User-confirmed Network acceptance. |
| Explicit 404 sends only explicit Review GET | PASS | User-confirmed Network acceptance. |
| No POST/PUT/PATCH/DELETE in Review flow | PASS | Production module scan is NONE; user-confirmed acceptance. |
| QA fixture requests occur only in harness | PASS | Isolation scan verified; user-confirmed acceptance. |

## Interaction and responsive checks

| Check | Result | Evidence / notes |
|---|---|---|
| Traditional ↔ simulator mode switch | PASS | User-confirmed acceptance. |
| Back / Forward / popstate | PASS | User-confirmed acceptance. |
| Safe deep-link contains no absolute path | PASS | Generated URL uses safe project/timeline/chapter keys. |
| Keyboard focus reaches mode buttons and key controls | PASS | User-confirmed acceptance. |
| Stale response does not overwrite new context | PASS | User-confirmed acceptance; existing request-generation guard retained. |
| 768px has no card overlap/core overflow | PASS | User-confirmed acceptance; no saved screenshot. |
| 390px `未提供` is not vertically broken | PASS | User-confirmed acceptance; no saved screenshot. |
| Authoritative and model supplement are visually separate | PASS | Visible QA screenshot supports separation. |
| `unresolved` appears for conflicts | PASS | User-confirmed fixture sweep. |

## Sign-off

- Human operator: user
- Result: `PASSED`
- Evidence record: [BROWSER_QA_EVIDENCE.md](BROWSER_QA_EVIDENCE.md), observed 2026-07-22 in Microsoft Edge via the ChatGPT extension bridge. Network acceptance was completed manually by the user; the bridge does not expose a HAR/Network-panel export.
