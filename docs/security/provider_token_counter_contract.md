# Provider Token Counter Contract

## Rule

An exact counter is a provider/model-specific, offline implementation of
`ProviderTokenCounter`. It receives the same immutable `ProviderRequest` whose
`canonical_payload()` is passed to the adapter. Character counts, generic
tokenizers, online lookup, model-name guessing, and silent fallback are not
exact counters.

Each counter declares stable `counter_id` and `counter_revision` values and
must explicitly support a `(provider_id, model_id)` pair. Unknown pairs return
no counter and block with `MODEL_TOKENIZER_UNSUPPORTED`. Exceptions, negative
values, and non-integers block with `INPUT_TOKEN_BUDGET_UNAVAILABLE`; a valid
count above the per-child ceiling blocks with `INPUT_TOKEN_BUDGET_EXCEEDED`
before `generate()`.

## Canonical request

`ProviderRequest.canonical_payload()` currently serializes the actual
OpenAI-compatible Chat Completions body: model, system/user messages, stream
false, temperature, optional max tokens, and optional response format. The
OpenAI-compatible adapter sends that exact dictionary. Counting and sending
therefore cannot independently rebuild different payloads.

The request fingerprint binds provider/model, profile revision, canonical
payload, counter id, and counter revision. Prompt, schema, generation setting,
profile, or counter changes alter the fingerprint. The envelope itself,
prompts, source text, and schema content are private and are not placed in
public readiness, tickets, audit, URLs, or logs.

## Persistence

Counter id/revision participate in the profile-registry revision. Consent
tickets and attempt audit records retain only these safe identifiers. Changing
the counter revision changes the registry revision, invalidating an unused old
ticket through the existing profile-revalidation Gate.

No production counter is registered in 0D3C3 because the repository has no
verified target-model tokenizer. Production Live remains blocked and
default-off.
