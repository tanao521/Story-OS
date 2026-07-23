# DeepSeek Conservative Readiness Contract

## Invariant

`exact_token_counter_available` and
`conservative_token_budget_available` are mutually exclusive. Conservative
readiness is a server-owned safety estimate, not Provider exactness.

## Public projection

```json
{
  "token_budget_mode": "conservative",
  "exact_token_counter_available": false,
  "conservative_token_budget_available": false,
  "conservative_policy_label": "DeepSeek V4 Flash Strict Conservative",
  "conservative_policy_revision": "owner-proposal-1",
  "text_counter_label": "DeepSeek-provided V3 Layer-A text asset",
  "text_counter_revision": "sha256-c954ca6f6e54",
  "max_text_tokens": 2048,
  "max_conservative_input_tokens": 3584,
  "thinking_mode": "disabled",
  "structured_output_mode": "json_object",
  "ready_for_consent": false,
  "ready_for_live_execution": false,
  "safe_readiness_code": "CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE"
}
```

The B0 projection remains unavailable because no implementation is authorized,
the asset license is unresolved, and the canonical payload lacks explicit
thinking and JSON Output fields.

## Required future binding

Policy id/revision, counter id/revision, profile revision, exact model id,
thinking mode, structured-output mode, output ceiling, canonical-payload hash,
and source/context fingerprints must bind the Registry, Ticket, Audit, Run,
and request fingerprint. Any mismatch rejects consent/execution.

The object counted must be the exact immutable canonical object sent. The
adapter may not add `thinking`, `response_format`, messages, or defaults after
counting.

Safe codes:

- `CONSERVATIVE_TOKEN_BUDGET_AVAILABLE`
- `CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE`
- `CONSERVATIVE_TOKEN_BUDGET_EXCEEDED`

## UI contract

Display:

- ??? Token ???;
- ??? Provider ?????;
- ??? Live ????;
- ?????????;
- Strict limits and policy revision.

Never display ?Exact?, ?Billing accurate?, ??? V4 Tokenizer?, zero expected
cost, credential detail, or endpoint. Consent remains disabled in B0.

## Reconciliation privacy

Only safe numeric deltas, revisions, model id, fingerprint, and timestamp are
public/auditable. Prompt, text, credential, endpoint, response, paths, and raw
exceptions are prohibited.
