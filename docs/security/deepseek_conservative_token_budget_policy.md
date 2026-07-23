# DeepSeek Conservative Token Budget Policy

## Status and scope

**OWNER-APPROVED SAFETY POLICY PROPOSAL ? NOT PROVIDER TOKENIZATION FACT**

Target: DeepSeek / `deepseek-v4-flash` / Reader Persona child request.
This design is not an exact tokenizer, billing estimator, V4 tokenizer
mapping, or production registration. Exact and conservative readiness are
mutually exclusive.

## Recommended model: Hybrid Reserve

Two evaluated formulas:

1. Absolute:
   `text_tokens + chat + json + thinking + uncertainty`
2. Hybrid:
   `text_tokens + base + per_message * message_count
   + ceil(text_tokens * uncertainty_ratio) + json + thinking`

Recommend **Hybrid**. Absolute reserve is simpler but treats a two-token prompt
and a 2,048-token prompt as equally uncertain. Hybrid keeps a fixed framing
floor while increasing the safety margin with input size and message count.
Neither formula is a DeepSeek fact.

## Strict Tier proposal

| Field | Proposed value | Basis |
| --- | ---: | --- |
| `policy_id` | `deepseek-v4-flash-conservative-strict` | Owner policy |
| `policy_revision` | `owner-proposal-1` | Owner policy |
| `provider_id` / `model_id` | `deepseek` / `deepseek-v4-flash` | Owner selection |
| `text_counter_id` | `deepseek-v3-archive-layer-a` | Evidence label only |
| `text_counter_revision` | `sha256-c954ca6f6e54` | A0 audit baseline |
| `text_counter_scope` | `layer_a_text_only_non_exact` | Evidence boundary |
| `text_token_limit` | 2,048 | Owner policy |
| `fixed_base_reserve` | 512 | Owner policy |
| `per_message_reserve` | 64 | Owner policy |
| `uncertainty_ratio` | 25% | Owner policy |
| `structured_output_reserve_tokens` | 256 | Owner policy |
| `thinking_reserve_tokens` | 0, only with explicit disable | Owner policy |
| `max_conservative_input_tokens` | 3,584 | Owner policy |
| `max_output_tokens` | 512 | Owner policy |
| `max_total_tokens` | 4,096 | Owner policy |
| `max_provider_calls` | 1 per child | Existing safety posture |
| `timeout_seconds` | 60 | Existing safety posture |
| `post_call_reconciliation_required` | true | Owner policy |
| `cost_estimate_available` | false | Required safety truth |
| `retry_policy` / `fallback_policy` | `0` / `none` | Existing safety posture |

At the 2,048 text ceiling and two messages, the Hybrid estimate is 3,456,
leaving 128 tokens below the conservative input ceiling. Output is separately
capped at 512. These are Story OS limits, not DeepSeek context limits.

Strict is the only tier proposed for approval. Standard and Expanded remain
undefined and unauthorized until separately approved usage evidence exists.

## Server ownership and fail-closed rules

- The server owns every reserve and ceiling. A client may only lower a limit.
- Unknown provider/model, missing counter asset, invalid count, missing policy
  revision, or mismatched payload returns
  `CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE`.
- Over-limit returns `CONSERVATIVE_TOKEN_BUDGET_EXCEEDED` before Provider use.
- Availability returns `CONSERVATIVE_TOKEN_BUDGET_AVAILABLE`; it never sets
  `exact_token_counter_available=true`.
- No character-count fallback, retry, fallback model, automatic reserve change,
  or cost projection is permitted.
- Policy/counter/profile revisions enter the request fingerprint, Registry,
  Ticket, Audit, and Run; revision drift invalidates an old Ticket.

## Thinking and JSON Output

Official DeepSeek documentation defines
`thinking: {"type":"disabled"}` as non-thinking and states that thinking
defaults to enabled. Strict policy therefore requires explicit `disabled`.
Relying on the default is forbidden.

JSON Output requires `response_format: {"type":"json_object"}`, the word
`json` plus a format example in the prompt, and a bounded `max_tokens`.
DeepSeek warns that empty content may occur. Current Story OS constructs the
real request with `structured_output_schema=None` and has no `thinking` field.
Thus `count payload == send payload` is not yet satisfied and implementation
remains blocked.

The reviewed official pages establish both controls but do not explicitly
promise the combined behavior of thinking mode plus JSON Output, nor disclose
whether `response_format` adds billed input tokens. Strict avoids the first
ambiguity by explicitly disabling thinking and covers the second only as
non-exact uncertainty; it does not claim the 256 reserve is Provider-derived.

## V3 Archive boundary and license

The A0 asset may supply only deterministic Layer-A text counts and offline
fixtures. It must never be described as a V4 exact tokenizer or used for Chat
overhead, JSON overhead, or billed equality.

Because its license remains unidentified, it must not be committed, bundled,
redistributed, or made a production dependency. A later implementation needs
a separately approved, compliant deployment-provisioning mechanism or remains
blocked.

## Post-call reconciliation design

Append-only safe record:

- local text tokens;
- conservative estimated tokens;
- Provider prompt tokens;
- signed difference tokens and ratio;
- policy/profile/counter revisions;
- model id, safe request fingerprint, timestamp.

Never store prompt, chapter text, credential, endpoint, raw response, or raw
exception. Reconciliation cannot retry, change policy, raise limits, or claim
local exactness.

Before considering Standard, propose **12?20 independent fixed fixtures**,
covering Chinese, English, mixed text, emoji/newlines, long text, and JSON
Output. Each fixture gets one call, no retry/fallback, complete Provider usage,
and no observed underestimation beyond the approved reserve. Evaluate maximum
underestimation, not only mean error. Any reserve breach fails the policy;
sample insufficiency cannot relax it.
