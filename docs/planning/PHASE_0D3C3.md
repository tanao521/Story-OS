# Phase 0D3C3 — Provider Operational Readiness & Exact Token Budgeting

## Outcome

**PARTIALLY PASSED.** Provider readiness infrastructure, canonical request
serialization, exact-counter registry seam, safe public projection, offline
dry-run, revision invalidation, frontend status copy, and security tests are
complete. The repository does not contain a verified tokenizer for a concrete
real OpenAI-compatible model, so every real Profile remains safely blocked.

## Implementation

- `ProviderRequest.canonical_payload()` is now the single request body used by
  both counting seams and the OpenAI-compatible adapter.
- `ProviderTokenCounterRegistry` resolves only explicit provider/model support;
  unknown models never fall back to approximation.
- `ProviderOperationalReadiness` separates internal credential readiness from
  a safe public projection.
- `prepare_live_request_dry_run()` performs offline fingerprint/count/budget
  checks without Provider, network, consent, ownership, audit, or Run writes.
- Counter id/revision enter registry revision, consent tickets, and attempt
  audits. Revision drift invalidates old tickets.
- Budget-blocked child executions now report zero actual Provider calls.
- Live Plan shows safe exact-counter/readiness metadata while retaining the
  existing default-off execution Gate.

No dependency was added. No real tokenizer, Provider, credential, network,
token, or price service was used.

## Stop

Do not enter a real Canary or enable production Live. A future separately
authorized phase must first select and verify one concrete provider/model
tokenizer offline.
