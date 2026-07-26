# Provider Operational Readiness

## Adapter audit

Story OS currently has one real adapter family:
`OpenAICompatibleModelPersonaProvider`, using one `requests.post` call to the
Chat Completions endpoint. It has retry 0 and fallback none. Mock and injected
test providers are not production adapters.

The environment contains the low-level `tokenizers` package transitively via
the existing vector stack, but no verified target chat-model tokenizer asset.
`tiktoken` and `transformers` are not installed in the active Python runtime.
No real Provider profile is configured. A generic Hugging Face tokenizer or
character count cannot prove OpenAI-compatible request tokenization, including
message overhead and model alias/version behavior.

## Readiness model

Internal `ProviderOperationalReadiness` contains profile revision, an internal
credential-configured boolean, exact-counter metadata, serialization/budget/
structured-output support, default-off capability state, readiness booleans,
and a safe code. The public projection excludes credential detail, endpoint,
base URL, environment names, raw config/exception, prompt, source, and paths.

Public fields are limited to profile/display/provider/model labels, enabled,
exact-counter availability and safe counter label/revision, budget and
structured-output support, consent/live readiness, and safe readiness code.
Counter-ready while capability-off is represented as
`PROFILE_READY_CAPABILITY_DISABLED`.

## Offline dry-run

`prepare_live_request_dry_run()` receives an already canonical request, an
explicit counter, and a ceiling. It fingerprints, counts, and applies the
budget without resolving credentials, issuing consent, creating ownership,
writing Runs/audits, calling a Provider, or accessing network. Unknown models
and counter failures block safely.

## 0D3C3 decision

Infrastructure and safe blocking are ready, but no real profile has a trusted
exact counter. Therefore this phase is **PARTIALLY PASSED**. No production Live
enablement or Canary is authorized. The next step remains blocked until a
specific provider/model tokenizer and canonical-message overhead can be
verified offline and version-locked.
# Conservative readiness addition

The DeepSeek Strict Profile now has a distinct `token_budget_mode:
conservative` projection. It never sets exact readiness true. Without a
validated externally provisioned Layer-A counter it returns
`CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE`; Consent and Live remain false.
