# Phase 0D3C2-P — Controlled Live Execution Preflight

## Status

**BLOCKED — preflight completed.** This is the required truthful outcome, not
an implementation failure. The current production surface stays Mock-only and
no Live UI was opened.

## Scope observed

0D3C1 remains **PASSED**: its production request is fixed to `mode=mock`,
`execution_profile=mock`, and `max_provider_calls=0`, with no Live toggle,
credential input, provider endpoint input, retry, or fallback control.

The existing dormant server capability accepts Live through:

- `POST /api/reader-persona/model-panel/plan`
- `POST /api/reader-persona/model-panel/runs`

Both parse through `_panel_request_from_http()` and use
`ModelPersonaPanelExecutionService`; child execution is performed by
`ModelPersonaExecutionService`. Live and Mock share the execution contracts.
The Review service only reads saved runs and keeps deterministic authoritative
fields separate from model supplements.

## Gate answers

| Question | Verified answer |
| --- | --- |
| Is `mode=live` supported server-side? | Yes, as the `ExecutionMode.LIVE` enum value; no current production UI exposes it. |
| Is explicit allowance required? | Yes. `allow_model_call` defaults to false and a Live request without true is blocked as `MODEL_CALL_BLOCKED` before provider resolution/call. |
| Is a profile required/validated? | Yes. The request names a profile; the server registry resolves profile/provider/model. Unknown profile blocks as `INVALID_PROFILE`; a disabled/unconfigured profile blocks as `PROVIDER_NOT_CONFIGURED`. |
| Are provider/model client-selectable? | Not directly. The parser forbids credential/endpoint configuration fields and the registry supplies provider/model. The profile name is still client input and the registry may drift with server environment configuration. |
| Are credentials server-only? | Yes in the inspected path. The preflight inspected variable names only and printed no values. No matching provider-related variable name was present in this process. |
| Is the call budget hard bounded? | Yes. Personas are capped at 5; `max_provider_calls` is an integer from 0 through 5; Plan blocks expected Live cache misses above the chosen cap. |
| Is a token/cost ceiling available? | No. Output-token/timeout profile parameters exist, but there is no aggregate token budget, price provenance, monetary ceiling, or reliable pre-call cost estimate. |
| Is Plan read-only? | Yes. It builds/validates snapshot and cache information but does not call a provider or create a Run. |
| Are records immutable? | Yes. Panel and child stores append new ids; successful, partial, failed, invalid, and blocked outcomes are represented. |
| Is source verified before run? | Yes. `execute()` recomputes Plan immediately before child execution; saved reviews evaluate staleness from stored fingerprints/hashes. A change during sequential execution still needs a defined post-run race policy. |
| Is retry/fallback present? | No automatic retry/fallback was found in the inspected execution path. This must become an explicit future policy, not an assumption. |
| Is cancellation safe? | No. Browser abort cancels waiting, not proven server/provider work. Durable in-progress, cancellation, and response-loss semantics are absent. |
| Is Live idempotent? | No. This is the blocking finding. |

## Reproducible blocking evidence

`story-os-demo/tests/test_phase0d3c2_preflight.py` executes an injected,
in-process fake provider in a `tmp_path` project. It proves that two identical
Live executions with `force=true` receive different panel ids and make two
provider calls. The system computes a panel fingerprint but does not atomically
look up/reserve it; it has no idempotency key, in-flight lock, or response-loss
recovery endpoint. A browser double submission, refresh, direct POST, or
concurrent request can therefore duplicate a billable operation.

This alone meets the preflight BLOCKED rule. Additional blockers are the
body-supplied legacy `project_root`, absence of server-side consent/audit
records, lack of token/cost ceiling, and undefined cancellation/reconciliation.

## Safety evidence

- Preflight tests use only an isolated temporary project and injected fake
  providers. A socket-creation canary makes any attempted socket creation fail.
- No real Provider, external network request, credential value, token use, Live
  UI, user project Run, story write, Canon/Summary change, Chroma mutation, or
  Obsidian operation occurred.
- Provider exception test uses a sentinel string and verifies it is reduced to
  `PROVIDER_ERROR` / `Provider request failed` without persisting the sentinel.
- Protection observation after validation: Chroma **6/6** matches its baseline;
  authority assets **16**; Obsidian bindings **30**; real model/panel Run JSON
  counts **0/0**.

## Artifacts

- `docs/security/live_panel_execution_risk_matrix.md`
- `docs/design/live_panel_execution_contract_map.md`
- `docs/design/live_panel_execution_ui_gate_spec.md`
- `docs/planning/PHASE_0D3C2_IMPLEMENTATION_BRIEF.md`
- `story-os-demo/tests/test_phase0d3c2_preflight.py`

## Stop rule

Do not implement Live UI or trigger the current Live endpoint. The only
possible follow-up is separately authorized **0D3C2-A Server Hardening**.
