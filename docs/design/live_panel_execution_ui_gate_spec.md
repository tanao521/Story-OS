# Live Panel Execution UI Gate Specification

Phase 0D3C2-B implements the read-only planning and consent portion and
0D3C2-C adds a separately gated, default-off controlled Run handoff. The
production UI can inspect safe projections and create an expiring consent
ticket; execution is visible only when the server capability is enabled and a
second explicit confirmation is checked.

## Entry gate

Show a Live entry only when all server-provided checks are true:

1. A selected, safe project key and matching project/timeline/chapter context.
2. A source snapshot is available and has a current server fingerprint.
3. The requested Personas are enabled and at most five; server order is shown.
4. An enabled public execution-profile projection is available. It may show a
   human label, provider label, model label, timeout, and output cap, but never
   endpoint identity, credential status details, secret, raw exception, or
   absolute path.
5. The consent endpoint is available only after the user opens the plan and
   checks the explicit consent box. A server-generated ticket then states the
   exact allowed profile, scope, ordered Personas, maximum calls, token/cost
   policy, expiry, and private idempotency key.

If any condition fails, show a safe blocked code/reason and provide no submit
control. Client state, URL parameters, and local storage cannot create a
ticket.

## Confirmation gate

The confirmation surface must state, without ambiguity:

- **Live preparation** (visually different from Mock); this phase does not
  execute Live model work.
- selected profile/provider/model safe labels;
- selected Persona count and server order;
- expected calls, hard maximum calls, cache assumptions, and a truthful
  token/cost estimate or the explicit text “estimate unavailable”; never show
  a fabricated price or zero cost;
- source/version/context being sent;
- results can be completed, partial, failed, or stale; partial/failed attempts
  are retained as immutable records;
- no automatic retry, fallback provider, story edit, Canon/Summary edit, or
  Obsidian/Chroma write;
- explicit consent text, version, and timestamp.

Confirmation must create or bind the implemented server-side consent record.
Toggling a browser checkbox alone is insufficient.

## Submission gate

- Submit exactly one consent request with safe scope/profile/persona/budget
  fields. The returned ticket and idempotency key remain closure-memory only;
  the client does not submit a run request in 0D3C2-B.
- The server atomically returns the existing in-progress/completed result for a
  repeated key/fingerprint; it never starts a second provider call.
- No automatic retry follows click, refresh, Back/Forward, network timeout, or
  response loss. A recovery screen queries the idempotency/status endpoint.
- Browser abort means “stopped waiting” unless the server reports a completed
  cancellation. The UI must not claim the provider call stopped merely because
  the page navigated away.
- Never send API keys, endpoints, provider/model identifiers, project roots,
  or source text from the UI.

## Result gate

Before execution, display a safe shortened ticket id, issued/expiry status,
server budget, and the explicit “no model executed / Provider calls 0 / Token
0” result. After a controlled Run, display the persistent LIVE badge and safe
status/result. Full ticket and idempotency values remain module-private and
never enter DOM attributes, storage, logs, clipboard, or analytics; only the
safe final `panel_execution_id` may enter the explicit Review URL.

## Controlled Run gate

- The server capability projection is default-off and returns
  `LIVE_EXECUTION_DISABLED` when disabled. URL, storage, client variables, and
  request bodies cannot enable it.
- The Run control is shown only for a current issued, unexpired ticket whose
  scope/Persona/profile/budget fingerprint still matches, and only after a
  second unchecked-by-default confirmation.
- Exactly one POST is sent with `{project_key, ticket_id}` and
  `X-StoryOS-Idempotency-Key`. No client override, retry, fallback, optimistic
  execution id, or automatic POST is allowed.
- An uncertain response exposes a user-triggered status GET recovery action.
  Recovery never sends a second POST. `reconciliation_required` is surfaced as
  requiring review, not retry.
- Final results clear the opaque ticket/key, refresh Saved Runs, and hand off
  only a validated `panel_execution_id` to explicit Review. Review failure
  never triggers another Run POST or automatic fallback.

Mock and Live must retain distinct badge, confirmation, saved-run metadata,
and result copy so cached Mock output cannot be mistaken for billable Live
output.

## RC context-integrity seal

The module stores the ticket's project/timeline/chapter scope only in closure
memory. The response generation and current authoritative context must still
match before `panel_execution_id` is written to history. If the user changes
context while a POST is in flight or during GET recovery, the UI must not
attach that old Run to the new context, dispatch the Saved Run refresh event,
or issue another POST. It reports the final safe status and directs the user to
the original context's Saved Runs.

## Provider readiness display

Live Plan may display only exact-counter availability, safe counter label and
short revision, budget/structured-output support, consent/live readiness, and a
safe code. It must never show credential configuration, endpoint, environment
name, tokenizer path, or raw configuration. Counter-ready with capability-off
must explicitly say “Provider readiness passed” and “Production Live remains
disabled”. This display does not create consent or invoke Run.
# B1 non-exact wording

Conservative profiles display “保守 Token 预算”, “不是 Provider 精确计数”,
Strict Policy limits, explicit thinking-off, JSON Object, unavailable cost, and
“生产 Live 仍关闭”. No client enablement control is provided.
