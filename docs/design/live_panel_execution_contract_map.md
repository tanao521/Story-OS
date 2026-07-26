# Live Panel Execution Contract Map

## Server hardening status

0D3C2-C adds a default-off controlled Live Run caller to the production
Simulator surface. It may execute only after a server-enabled capability and
second explicit confirmation; recovery is GET-only and final handoff uses
only a safe execution id.

## Entry points

- Plan: `POST /api/reader-persona/model-panel/plan` ->
  `_panel_request_from_http()` -> `ModelPersonaPanelExecutionService.plan()`.
- Legacy Panel and single-Persona routes reject `mode=live` with
  `LIVE_REQUIRES_CONSENT_TICKET` before project/provider resolution.
- Live consent: `POST /api/reader-persona/model-panel/live/consent` ->
  `LivePanelExecutionService.issue_consent()` (read-only plan only).
- Live run: `POST /api/reader-persona/model-panel/live/runs` -> atomic ticket
  reservation -> Panel/child execution.
- Recovery: `GET /api/reader-persona/model-panel/live/status/{ticket_id}` with
  `X-StoryOS-Idempotency-Key`; safe status only.
- Review: existing GET review routes load saved results only. They do not run a
  provider and preserve authoritative deterministic fields separately from the
  model supplement.

The Mock and Live paths share contracts, but 0D3C1 production UI sends only
`mode=mock`, `execution_profile=mock`, and `max_provider_calls=0`.

## Request boundary

| Field | Current origin | Server rule | Future Live rule |
| --- | --- | --- | --- |
| `persona_ids` | Client selection | non-empty, known, enabled, no duplicates; maximum 5; registry determines order | Keep; display server order before consent. |
| `chapter_id`, `source_version_id` | Client scope selection | snapshot/context validation occurs in plan; execute recomputes plan immediately | Bind to selected context and consent ticket. |
| `mode` | HTTP body, currently fixed to Mock by UI | legacy Live is rejected | Live requires an issued consent ticket. |
| `execution_profile` | HTTP body profile name | must exist in server registry | Public UI receives a safe projection, not provider config or endpoint identity. |
| `allow_model_call` | internal request only | Live rejects unless true | Ticket service sets it only after server consent; defensive gate remains. |
| `max_provider_calls` | HTTP body, default 1 | integer 0..5; plan rejects expected Live calls above it | Server issue/cap value in consent; no user increase after confirmation. |
| `force` | legacy Mock/internal only | Live schema rejects it | Never expose it for public Live. |
| `project_id`, `timeline_id` | derived from selected project `state.json` | service checks request scope matches state | Keep server-derived. |
| `project_key` | safe UI identifier | resolved by project manager | Keep only this selected-project route. |
| `project_root` | legacy Mock-only body input | Live routes reject it before resolution | Never accept it for Live. |

Forbidden client keys today: `api_key`, `authorization`, `base_url`,
`endpoint`, `provider_secret`, and `provider_config`. Future schemas must also
reject provider id/model id/endpoint identity and all credential aliases.

## Profile and provider boundary

`ModelPersonaExecutionService` owns the execution-profile registry. A profile
binds provider type/id, model id, generation parameters, timeout, enabled
state, and an endpoint identity. Credentials are resolved by server-side
environment configuration only; request data does not carry them. A profile
name is allowlisted by registry lookup. A safe registry revision is now
persisted to ticket, Panel Run, and audit; registry drift invalidates an
unconsumed ticket. The public projection excludes endpoint identity,
environment names, credential state, and raw parameters.

## Plan / run / review semantics

| Operation | Writes? | Provider call? | Required public output |
| --- | --- | --- | --- |
| Plan | No | No | ordered Personas, cache hit/miss, expected calls, maximum calls, safe blocked code/reason. |
| Run | immutable Panel + child records | Live cache misses only | execution id, mode badge, profile label, expected/actual calls, status, nullable usage completeness, safe error code. |
| Explicit Review | No | No | authoritative panel data, model supplement, staleness, explicit run identity; no automatic fallback. |

Panel statuses are `completed`, `partially_completed`, `failed`, `blocked`, and
`invalid_output`. Review staleness is `current`, `partially_stale`, `stale`, or
`source_missing`. Provider failures map to safe codes such as
`PROVIDER_TIMEOUT`, `PROVIDER_AUTH_ERROR`, `PROVIDER_RATE_LIMITED`, and
`PROVIDER_ERROR`; invalid output uses `MODEL_OUTPUT_INVALID` or grounding
codes. Ticket-bound status now defines cancellation, in-progress, and
reconciliation semantics without automatic retry.

## Usage, audit, and URL handoff

Usage is provider-reported and nullable. Panel aggregation distinguishes
completeness; missing data must remain `未提供`/unavailable and must never be
shown as zero. There is no cost field or defensible price estimate today.

Saved records include fingerprints, profile/model/provider metadata, run
status, timestamps, usage, and error code. They intentionally exclude prompts,
chapter text, raw provider response, credential values, and paths. Live now
adds immutable consent/attempt audit records and atomic ownership. An exact
provider-owned input token counter is required before a Live call; absent
counter blocks safely. Cost remains unavailable/null until a reliable price
source is approved.

After a successful run, the only handoff is the returned real
`panel_execution_id` in an explicit safe URL. No automatic review fallback, no
second POST, and no URL containing an absolute path are permitted.

## RC-sealed aggregation and context rules

- A failed child keeps its safe code. If every failing child has the same code,
  the Panel and Live ownership result retain that code; mixed failure classes
  collapse to `PROVIDER_ERROR`.
- Provider exceptions and raw output never become Panel, audit, ownership, or
  public response content.
- Missing usage is persisted as nullable fields with `partial` completeness;
  it is never converted to zero. No cost value is synthesized.
- The frontend privately binds the issued project/timeline/chapter scope to the
  ticket. A final response hands off only when that scope is still current. A
  stale response clears the private handle and reports the final result without
  changing URL/history or dispatching a cross-context Saved Run event.

## 0D3C3 readiness boundary

The canonical Provider request owns the final Chat Completions payload and is
shared by exact counting and `generate()`. A counter must explicitly support
the server-selected provider/model; unknown models block without approximation.
Safe counter id/revision enter registry/ticket/audit metadata, while prompts,
schemas, credentials, endpoint and paths remain private. The existing profiles
GET is the read-only readiness projection; it does not enable Live.
# B1 conservative bindings

Conservative Registry, Ticket and Audit records bind provider/model,
profile/policy/counter revisions and scope, canonical live-envelope hash,
thinking mode, structured-output mode, source fingerprint, and context
fingerprint. Public projections contain safe labels and revisions only.
