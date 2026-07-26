# Provider Tokenizer Evidence Log

Audit date: 2026-07-23. Public sources were restricted to official Provider,
SDK, tokenizer, and official organization repositories.

## Repository and local runtime

| Evidence source | Version/date | Exact claim supported | Remaining uncertainty |
| --- | --- | --- | --- |
| Story OS provider adapter and canonical request code | workspace at audit time | Live Panel has one OpenAI-compatible Chat Completions adapter; it sends model, two messages, stream, temperature, optional max tokens/response format | No owner-selected real Provider/model |
| Installed package metadata | local runtime, 2026-07-23 | `tokenizers` 0.23.1 and `requests` 2.34.2 are installed; `tiktoken` and `transformers` are absent | Installed `tokenizers` has no selected target assets and proves no hosted API framing |
| `pyproject.toml` and `uv.lock` hashes | before/after preflight | Dependency files remained byte-identical | None |
| Environment presence-only inspection | 2026-07-23 | Live Provider/model/base configuration and capability are not configured | Values were not read or printed |

## DeepSeek official evidence

| Evidence source | Version/date | Exact claim supported | Remaining uncertainty |
| --- | --- | --- | --- |
| [DeepSeek API first-call/model documentation](https://api-docs.deepseek.com/quick_start/pricing-details-usd/) | accessed 2026-07-23 | Current API model ids include `deepseek-v4-flash` and `deepseek-v4-pro`; legacy aliases are being retired; API is OpenAI-compatible | No statement binds the offline tokenizer archive to V4 Chat framing/schema billing |
| [DeepSeek token usage documentation](https://api-docs.deepseek.com/quick_start/token_usage/) | accessed 2026-07-23 | An offline tokenizer archive is offered; character/token ratios are approximate; actual usage is the response usage | Archive version/license, V4 mapping, message overhead, schema overhead, and billing equality are not established |
| [DeepSeek API change log](https://api-docs.deepseek.com/updates/) | 2026-04-24 entry | Model aliases and mappings change over time; V4 introduced new exact API ids | Stable tokenizer revision for those API ids is not documented |
| [Official DeepSeek-V3 repository](https://github.com/deepseek-ai/DeepSeek-V3) | accessed 2026-07-23 | Open-source V3 assets are large and local inference guidance is Linux-oriented; repository is MIT | V3 open weights/tokenizer are not proof of hosted V4 billing behavior |

Decision: reject for Live exact budgeting. Owner selection and V4-specific
tokenizer/framing evidence are missing.

### A0 Archive inspection, 2026-07-23

The Owner selected `deepseek-v4-flash`. The official Token Usage CDN asset was
downloaded and audited:

- `deepseek_v3_tokenizer.zip`
- 1,979,745 bytes
- SHA-256
  `c954ca6f6e54281d72d3c27e2430cea7663f81292b39982e2f97890c66c302de`
- fixed BPE JSON plus V3 chat template;
- no V4 model mapping, license, version manifest, or billing-equality rule.

An isolated direct JSON-tokenizer demo proved only deterministic text encoding.
No Provider call or credential access occurred. The detailed result is in
`deepseek_v4_tokenizer_verification.md` and
`deepseek_v4_tokenizer_supply_chain.md`.

## Alibaba/Qwen official evidence

| Evidence source | Version/date | Exact claim supported | Remaining uncertainty |
| --- | --- | --- | --- |
| [Alibaba Model Studio model list/pricing](https://help.aliyun.com/en/model-studio/model-pricing) | accessed 2026-07-23 | Hosted Qwen models include date-stamped snapshot ids such as `qwen-plus-2025-12-01`; generic aliases map to snapshots and can drift | No official local tokenizer + complete hosted Chat/schema billing rule is provided on this page |
| [Official Qwen repository](https://github.com/QwenLM/Qwen) | accessed 2026-07-23 | Open-source Qwen supplies tokenizer/chat-template assets; older Qwen tokenizer is tiktoken-based and uses special tokens | Open-source model tokenizer/template does not prove the hosted qwen-plus snapshot's server framing or billing |

Decision: reject for Live exact budgeting. A hosted snapshot can be pinned, but
the exact tokenizer and complete API overhead cannot currently be pinned.

## OpenAI official evidence

| Evidence source | Version/date | Exact claim supported | Remaining uncertainty |
| --- | --- | --- | --- |
| [OpenAI tiktoken repository](https://github.com/openai/tiktoken) | accessed 2026-07-23 | Official MIT-licensed tokenizer; `encoding_for_model` exists; local text tokenization is supported | Package not installed; repository alone does not establish billing-exact message/schema overhead |
| [tiktoken model mapping](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py) | accessed 2026-07-23 | GPT-4.1 prefixes map to `o200k_base`; unknown names can fail closed | Prefix matching can also accept nonexistent names; explicit allowlisting is still required |
| [OpenAI model documentation](https://platform.openai.com/docs/models/gpt-4%2C) | accessed 2026-07-23 | GPT-4.1 family and dated API snapshots exist | No reviewed contract guarantees that locally reconstructed Chat/schema tokens equal billed input tokens |

Decision: reject for Live exact budgeting. `tiktoken` would address text
encoding, not all four exactness layers required by this phase.

## Local probes

- Canonical payload shape probe: PASS; five expected top-level fields and two
  messages; no Provider call.
- Network canary: PASS; zero socket/HTTP calls.
- Dependency hashes: PASS; `pyproject.toml` and `uv.lock` unchanged.
- 0D3C3 + 0D3C2-RC focused tests: 32 passed.
- Compileall: passed.
