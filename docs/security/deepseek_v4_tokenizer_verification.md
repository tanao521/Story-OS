# DeepSeek V4 Flash Tokenizer Verification

Target decided by Owner:

- Provider: DeepSeek
- API model id: `deepseek-v4-flash`
- Protocol: OpenAI-compatible Chat Completions
- Use: Reader Persona Live Panel

Production Live remains default-off. No credential or Provider call was used.

## Official model evidence

DeepSeek's 2026-04-24 API documentation identifies
`deepseek-v4-flash` and `deepseek-v4-pro`, supports OpenAI
ChatCompletions, and describes both models as dual thinking/non-thinking:

- https://api-docs.deepseek.com/updates/
- https://api-docs.deepseek.com/news/news260424/
- https://api-docs.deepseek.com/quick_start/pricing-details-usd/

The Token Usage page still links an asset named
`deepseek_v3_tokenizer.zip`:

- https://api-docs.deepseek.com/quick_start/token_usage/

No reviewed official page or Archive file directly states that this V3
Archive is the tokenizer for V4 Flash/Pro. No official mapping promises that
the V4 models share that tokenizer or that its revision remains stable.

`V4_MAPPING_VERIFIED=false`.

## Four-layer result

### Layer A — Text encoding

**A_TEXT_ENCODING: VERIFIED FOR THE DOWNLOADED V3 ARCHIVE ONLY**

Using the installed `tokenizers` library to load the fixed
`tokenizer.json`, an isolated deterministic demo encoded English, Chinese,
mixed Unicode/emoji, newline, JSON text, and a long Reader Persona string.
Repeated token-id sequences matched; network attempts and filesystem writes
were zero.

This does not establish that V4 Flash uses the Archive.

### Layer B — Chat message framing

**B_CHAT_FRAMING: UNVERIFIED**

The Archive includes a V3-era chat template with user/assistant/tool special
tokens. It does not declare V4 Flash, thinking/non-thinking mode behavior, API
server insertions, fixed per-message overhead, or equality to the hosted V4
Chat Completions serializer. The isolated JSON tokenizer cannot accept
messages or a model id.

### Layer C — Structured output / JSON Output

**C_STRUCTURED_OUTPUT: UNVERIFIED**

DeepSeek's official JSON Output guide requires
`response_format={"type":"json_object"}` and JSON guidance in the prompt:
https://api-docs.deepseek.com/guides/json_mode/

It does not specify whether hidden instructions or input tokens are added.
The Archive accepts text only. In current Story OS execution,
`structured_output_schema=None`, so the canonical payload does not send
`response_format` even when the execution Profile uses JSON output.

### Layer D — billed input equality

**D_BILLED_INPUT_EQUALITY: UNVERIFIED**

The official Token Usage page says actual processed tokens are based on the
model response usage. It does not promise:

`local full-request count == API usage.prompt_tokens`.

No official rule covers hidden server tokens, thinking/non-thinking framing,
JSON Output overhead, or cache-related billing.

## Story OS payload compatibility

| Story OS field | DeepSeek V4 contract | Compatible | Notes |
| --- | --- | --- | --- |
| `model` | `deepseek-v4-flash` | Conditional | Owner target is explicit; production Profile is not integrated |
| `messages` | system/user messages | Yes structurally | Hosted V4 framing/token overhead unverified |
| `stream` | boolean | Yes | Story OS uses false |
| `temperature` | accepted but ignored in thinking mode | No deterministic guarantee | V4 thinking defaults enabled |
| `max_tokens` | supported | Yes structurally | Does not solve input counting |
| `response_format` | JSON Output uses `json_object` | Not currently sent | Execution constructs `structured_output_schema=None` |
| `thinking` | enabled/disabled object | Missing | Official default is enabled |
| `reasoning_effort` | high/max in thinking mode | Missing | Not relevant if Reader Persona explicitly fixes non-thinking |
| timeout | HTTP client setting | Compatible | Not part of token payload |

Reader Persona should not rely on the Provider's thinking default. A future
integration would need an Owner-approved explicit non-thinking policy and a
canonical payload change, followed by fresh payload/tokenizer evidence. A0
does not implement it.

## Decision

**BLOCKED — INSUFFICIENT V4 EXACTNESS EVIDENCE**

Layer A for the old Archive is not enough. V4 mapping, license, Layer B,
Layer C, and Layer D remain unverified. Do not register a production counter,
mark the Profile ready, enter 0D3C4-A, or run a Canary.

### Option 1 — Strict Exact Gate

Keep the real Profile blocked and wait for official V4-specific tokenizer,
framing, JSON-output overhead, billing-equality, revision, and license evidence.

### Option 2 — Conservative Budget Policy Proposal

Only under a separate Owner decision: official text tokenizer, documented
framing where available, fixed reserve, lower hard ceiling, and post-call usage
reconciliation. This is not exact and must not set
`exact_token_counter_available=true`. A separate readiness type such as
`conservative_token_budget_available` would be required.

