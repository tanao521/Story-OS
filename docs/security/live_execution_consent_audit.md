# Live Execution Consent and Attempt Audit

## Consent ticket

`LiveExecutionConsentTicket` is server generated with an unguessable ticket id
and idempotency key. It is immutable and expires after five minutes. It binds:

- project, timeline, chapter, source version, source/context fingerprints;
- server-ordered Persona ids;
- profile id and safe registry revision;
- bounded call/token/cost policy;
- consent text version, issue/expiry time, and canonical request fingerprint.

Tickets contain no provider endpoint, credential, environment-variable name,
prompt, chapter text, raw response, raw exception, or absolute path.

## Attempt audit

Every ticket execution decision appends a distinct immutable
`LiveExecutionAttemptAudit` under
`data/simulator/live_panel_execution/attempt_audit/`. It records only safe
scope/fingerprint/profile/budget/consent metadata, timestamps, state, panel id,
safe error code, actual provider calls, and usage completeness. It records
rejected, expired, blocked, cancelled, in-progress, completed, partial, failed,
and reconciliation outcomes.

The audit is separate from Panel Run records. A response-loss recovery reads
ownership/status and does not create a second attempt or provider call.

## Cancellation semantics

`POST /api/reader-persona/model-panel/live/cancel` is ticket-bound. Before
ownership begins it sets `cancelled` and prevents any provider call. After a
provider call may be underway it records only `cancel_requested`; it never
claims that a remote provider was stopped. A final provider result remains the
final execution state. No automatic retry follows cancellation.

## Redaction evidence

The isolated failure test sends an in-memory sentinel through a fake provider
exception and asserts it is absent from every persisted JSON record. HTTP
routes use generic safe errors for unexpected failures and public projections
omit endpoint identity, credential state, and internal class details.
