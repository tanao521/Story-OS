# Live Execution Budget Policy

## Server-owned policy

`LiveExecutionBudgetPolicy` is created by the server for the selected profile
and persisted in the consent ticket. Client input may request a lower/equal
call count only; it cannot raise a policy limit after consent.

| Field | Policy |
| --- | --- |
| `max_provider_calls` | hard maximum 5; ticket may be lower |
| `max_input_tokens` | 4096 exact provider-counted tokens per allowed call |
| `max_output_tokens` | selected profile's server-owned output cap per allowed call |
| `max_total_tokens` | sum of those maximum input/output caps across ticket calls |
| `timeout_seconds` | server-owned profile timeout passed to the provider adapter |
| retry policy | `0` |
| fallback policy | `none` |
| cost estimate | unavailable: `cost_estimate_available=false`, currency and maximum estimated cost are `null` |

No token number is derived from character count. Before a Live provider call,
`ModelPersonaExecutionService` requires the resolved provider to supply an
exact `count_request_tokens(canonical_request)` capability. The older two-prompt
shape remains supported only for injected regression providers. Missing,
invalid, unsupported-model, or over-cap counts block with
`INPUT_TOKEN_BUDGET_UNAVAILABLE`, `MODEL_TOKENIZER_UNSUPPORTED`, or
`INPUT_TOKEN_BUDGET_EXCEEDED` before calling the provider. The current
OpenAI-compatible adapter does not implement a verified real-model counter, so
it safely blocks rather than guessing.

Provider-reported post-call usage remains nullable and is stored/aggregated as
actual usage. Missing usage stays null/partial; it is never displayed or
recorded as zero. Price data is deliberately not fetched or invented.
## 0D3C3 exact-counter rule

The per-child input ceiling is evaluated against the same canonical
`ProviderRequest` payload sent by the adapter. Counter id/revision bind the
profile registry and consent/audit metadata. Unsupported models and counter
errors block before Provider execution; character approximation is forbidden.
No real counter is registered yet, so real Profiles remain blocked.
# Strict conservative mode

For `deepseek/deepseek-v4-flash`, B1 adds a non-exact Owner policy: 2,048 text,
3,584 conservative input, 512 output, 4,096 total, one call per child, 60
seconds, zero retry, no fallback, and unavailable cost. Client limits may only
lower these server ceilings.
