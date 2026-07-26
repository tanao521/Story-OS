# Live Panel Execution Risk Matrix

## Scope and decision

This is a read-only 0D3C2-P assessment of the existing server path. No real
provider, network request, credential value, or user project Run was used.

**Decision: BLOCKED.** The future Live UI must not be opened. The next eligible
work, if separately approved, is **0D3C2-A Server Hardening**.

| Risk | Existing control and evidence | Residual risk | Required mitigation | Severity | Gate |
| --- | --- | --- | --- | --- | --- |
| Browser tampering enables `mode=live` | The HTTP parser validates the mode; `ModelPersonaExecutionService.execute` rejects Live without `allow_model_call=True`. Fake-provider test proves the false gate produces `MODEL_CALL_BLOCKED` before a provider call. | The run endpoint is nevertheless directly reachable without the future UI. | Keep the server gate; bind Live authorization to a server-created consent ticket, not just a client boolean. | HIGH | REQUIRED |
| Arbitrary provider/model/endpoint injection | Requests name only an `execution_profile`; the profile registry supplies provider/model. The parser forbids `api_key`, `authorization`, `base_url`, `endpoint`, `provider_secret`, and `provider_config`. | `project_root` is still accepted by the legacy HTTP parser; `ExecutionProfile.to_dict()` contains `endpoint_identity` and must never be exposed in a Live UI. Environment changes can alter the default registry at process start. | Remove body-supplied `project_root` from Live endpoints; expose only an allowlisted public profile projection; record a server-side registry revision. | HIGH | BLOCKER |
| Credential disclosure | Provider credentials are resolved only in server configuration. Provider exception mapping returns a generic public error; fake sentinel test proves a provider exception string is not persisted. | The guarantee is not yet demonstrated across every adapter/logging path, and no dedicated redaction boundary/audit sink exists. | Add structured redaction tests for adapter, route, saved run, and logging paths; deny endpoint/secret fields at every schema boundary. | HIGH | REQUIRED |
| Excessive provider calls | Contract caps Personas at 5 and `max_provider_calls` at 5. Plan calculates cache hit/miss and rejects a plan whose expected Live calls exceed the requested cap. | No aggregate token budget, price table, or monetary ceiling exists. `force` can bypass cache. | Server-enforced token/cost ceiling per consented execution; remove or privilege-gate Live `force`. | HIGH | BLOCKER |
| Duplicate billing / response loss | Input and panel fingerprints are computed; ordinary completed child runs can be cache hits. | No idempotency key, in-flight lock, fingerprint lookup, or response-recovery query exists. Two identical `force=true` Live executions created distinct immutable runs and two fake provider calls. | Atomic idempotency registry keyed by scope + request fingerprint + server consent; in-flight ownership; replay-safe status lookup. | CRITICAL | BLOCKER |
| Concurrent duplicate submission | The current Mock UI disables its button while pending. | A second tab, refresh, direct POST, or concurrency is not server-deduplicated. Client AbortController cannot cancel server work. | Same atomic server idempotency mechanism; report an existing/in-progress run rather than sending a second call. | CRITICAL | BLOCKER |
| Retry or provider fallback | Current child execution has no automatic retry/fallback; a provider exception maps to a safe error code. | This is an implementation observation, not an enforced policy/audit contract for future adapters. | Encode retry count `0` and fallback `none` in the Live profile and audit record; reject any alternative until explicitly approved. | MEDIUM | REQUIRED |
| Timeout/cancellation ambiguity | Profiles contain a timeout field; status model represents failed/partial results. | Browser abort only stops waiting; no server cancellation token, durable in-flight state, or response-loss recovery exists. | Define provider timeout enforcement, cancellation semantics, persisted `cancelled`/`in_progress` state, and reconciliation procedure. | HIGH | BLOCKER |
| Partial/failed persistence | Child and Panel Run stores are append-only; Panel status supports completed, partially completed, failed, blocked, and invalid output. | No consent/audit event associates the triggering user, decision text, or declared budget with an immutable run. | Add separate append-only execution-attempt audit records, including consent version and final outcome. | HIGH | REQUIRED |
| Source/context race | Plan builds a deterministic snapshot; `execute()` recomputes its plan immediately before child calls. Review checks staleness from saved hashes/fingerprints and does not override authoritative fields. | A source can still change during a sequential execution. | Persist source snapshot/version at acceptance and define a post-run race outcome; never label changed-source output current. | MEDIUM | REQUIRED |
| Mock/Live confusion | 0D3C1 fixes the production UI to Mock only: `mode=mock`, profile `mock`, max calls `0`; no Live control exists. | A later UI could present similar output without a durable Live badge/consent record. | Follow the mandatory visual/state separation in `live_panel_execution_ui_gate_spec.md`. | HIGH | REQUIRED |
| Usage/cost misrepresentation | Provider usage is nullable and panel aggregation preserves completeness; no cost field is present. | There is no reliable pre-call token/cost estimate or post-call monetary accounting. | Show `unavailable` rather than zero; add server-owned estimate provenance and a hard cap before enabling Live. | HIGH | BLOCKER |
| User/project scope injection | Request `project_id`/`timeline_id` derive from the selected project state, and service checks scope consistency. | `project_root` in the HTTP body remains a legacy local-path selector. | Use authenticated/selected project context only; reject absolute paths and cross-scope selectors at Live entry. | HIGH | BLOCKER |

## Evidence set

- `story-os-demo/tests/test_phase0d3c2_preflight.py` uses only `tmp_path`, an
  injected in-process provider, and a socket-creation canary.
- The Live false gate, unknown/disabled profile, persona/call limits,
  read-only plan, safe provider-error reduction, and duplicate-force finding
  are covered by that suite.
- Environment inspection reported only provider-related **names**, and no
  matching name was present; no environment values were read or printed.
- The protected real project remained at Chroma 6/6 matching its baseline,
  16 authority assets, 30 Obsidian bindings, and 0/0 model/panel Run JSON.

This matrix is a safety assessment, not permission to use the existing Live
POST endpoint.
