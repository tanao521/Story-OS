# Phase 0D3C2-P Delivery Report

**Final result: BLOCKED (preflight complete; Live implementation not entered).**

## What was collected

| Check | Result |
| --- | --- |
| Existing preconditions | Collected: 0D3C1 is PASSED and remains Mock-only. |
| Live endpoint/service map | Collected: plan/run POST routes -> request parser -> Panel service -> child execution service; Review remains read-only. |
| Allow/profile/budget gates | Passed: false allowance blocks before call; unknown/disabled profiles block; Persona and provider-call caps are server validated. |
| Profile/provider allowlist | Partially passed: provider/model derive from server profile registry and restricted request fields; registry/default profile can drift with environment and public projection is not yet hardened. |
| Credential boundary | Passed for inspected path: server-side resolution only; no values read/printed; fake exception sentinel was not persisted. Broader log/audit redaction remains required. |
| Plan safety | Passed: unknown-profile Live plan test has no write/call; Plan is read-only. |
| Fake provider/network canary | Passed: injected provider is local; a patched socket creation path did not fire. |
| Immutable result/failure behavior | Collected: append-only child/Panel records and completed/partial/failed/blocked/invalid statuses exist. |
| Duplicate/idempotency | **Failed:** identical `force=true` executions made two fake provider calls and created two immutable panel ids. |
| Token/cost guard | **Failed:** no aggregate token budget, price estimate provenance, or cost ceiling. |
| Cancellation/recovery | **Failed:** no server cancellation/in-progress/idempotent response-loss recovery contract. |
| Production fixture fallback scan | Passed: none found. |
| Live UI/credential input scan | Passed: Mock request is fixed; no Live control or credential input exists. |
| Protected-data check | Passed: Chroma 6/6 baseline match; authority assets 16; Obsidian 30; real model/panel Runs 0/0. |

## Validation commands

Executed from `story-os-demo`:

```text
python -m pytest -q tests/test_phase0d2b1_model_persona_execution.py tests/test_phase0d2b2_model_persona_panel_execution.py tests/test_phase0d2b3_panel_review_model.py tests/test_phase0d3c2_preflight.py tests/test_phase0d3b1_simulator_panel_frontend.py tests/test_web_routes.py
126 passed in 8.64s

python -m compileall -q web system core
passed

node --check web/static/simulator-panel-run.js
node --check web/static/simulator-context-navigator.js
node --check web/static/simulator-panel-review.js
node --check web/static/app.js
passed
```

The focused preflight suite has seven tests: allowance rejection, read-only
unknown profile, disabled/unconfigured profile, hard call/persona limits,
duplicate-force evidence, network canary, and provider-error redaction.

## Key answers for handoff

- **Live endpoint/service:** `POST /api/reader-persona/model-panel/runs`;
  `ModelPersonaPanelExecutionService.execute()` then
  `ModelPersonaExecutionService.execute()`.
- **`allow_model_call`:** complete defensive server gate for the inspected
  service path; default false and false blocks Live.
- **Execution registry:** `model_persona_execution_service.py` server profile
  registry; profile binds provider/model/generation/timeout.
- **Provider/model allowlist:** profile-derived, not direct client input;
  harden profile projection and environment drift controls before Live.
- **Credential:** server configuration only; generic provider failure is
  reduced before persistence in the tested path.
- **Budget:** max calls is hard capped at five, but token/cost is not reliably
  estimated and has no ceiling.
- **Idempotency:** unsafe for Live; duplicate billing is possible.
- **Failure/timeout/cancel:** failures persist as immutable outcomes; timeout
  code mapping exists, but server cancellation, in-flight state, and recovery
  do not.
- **Usage:** provider-reported nullable values are aggregated with
  completeness; there is no cost field.
- **Audit:** run metadata includes fingerprints/status/profile/usage but does
  not include a dedicated consent/attempt audit record.
- **Source:** Plan is recomputed before run and review evaluates staleness;
  race semantics during execution need hardening.

## Prohibited actions not performed

No real OpenAI/DeepSeek/other provider call, external network request,
credential read/print, token consumption, Live UI, user project Run, story
asset write, Chroma/Obsidian operation, dependency installation, commit, push,
reset, clean, rebase, or Phase 0D3C2 implementation occurred.

## Next step

Stop here. The report recommends only a separately approved **0D3C2-A Server
Hardening** phase; do not proceed to a Live Plan UI or Live Run phase.
