# Phase 0D3C4 Integration Brief

## Status

**BLOCKED — INSUFFICIENT V4 EXACTNESS EVIDENCE**

The Owner selected DeepSeek / `deepseek-v4-flash`, but no offline tokenizer
integration is authorized. The official-page-linked Archive is V3-named,
unlicensed in-package, and lacks direct V4 mapping plus Layers B/C/D evidence.

## Minimum owner input required

Provide all of the following from official DeepSeek sources:

1. A V4 Flash-specific tokenizer/revision mapping.
2. License terms for the tokenizer Archive/assets.
3. Official evidence for Chat message framing and structured-output/schema
   overhead, not only plain-text BPE.
4. An official equality contract between complete local request count and
   billed `usage.prompt_tokens`.
5. Confirmation that runtime counting is fully offline and requires no dynamic
   download.

After those inputs exist, a new preflight should verify the evidence. Only a
pairing that passes all exactness layers may receive a separately authorized
0D3C4-A implementation plan.

No dependency proposal is made now because selecting a package before the
Provider/model decision would invert the safety Gate. In particular, the
existing generic `tokenizers` package is insufficient because it contains no
selected vocabulary/chat template and cannot prove hosted Provider billing.
