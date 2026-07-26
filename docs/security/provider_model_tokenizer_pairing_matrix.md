# Provider / Model / Tokenizer Pairing Matrix

Audit date: 2026-07-23. This matrix is a read-only preflight. It does not
select a production Provider, install a tokenizer, access credentials, call a
Provider, or authorize Live/Canary.

The project has no explicitly configured or owner-approved Live Panel
Provider/model. DeepSeek and Qwen appear elsewhere in Story OS product intent,
while OpenAI-compatible is a protocol adapter. None of those facts constitutes
an owner decision for Live Panel.

| Field | DeepSeek API candidate | Alibaba Model Studio Qwen candidate | OpenAI API candidate |
| --- | --- | --- | --- |
| Provider | DeepSeek | Alibaba Cloud Model Studio | OpenAI |
| API protocol | OpenAI-compatible Chat Completions | OpenAI-compatible API family | Chat Completions |
| Exact model id examined | `deepseek-v4-flash` | `qwen-plus-2025-12-01` | `gpt-4.1-2025-04-14` |
| Alias drift | Snapshot-like V4 id is better than legacy aliases; owner has not selected it | Snapshot id is pin-shaped; generic `qwen-plus` drifts | Dated snapshot is pin-shaped |
| Tokenizer package | Official DeepSeek offline tokenizer archive is advertised, but mapping to V4/API framing is not established | Open-source Qwen tokenizer evidence does not establish hosted qwen-plus API framing | Official `tiktoken` maps GPT-4.1 family to `o200k_base` |
| Tokenizer version | No V4-compatible pinned package/revision proven | No hosted qwen-plus tokenizer package/revision proven | Package can be pinned, but it is not installed |
| Offline | Archive/tokenizer could be local after separate acquisition | Possible only with separately acquired model tokenizer assets | Encoding can be local after installation/assets |
| Asset requirement | Additional archive/assets; not currently present | Additional tokenizer/model assets; not currently present | New package and encoding assets |
| Message overhead | No official V4 Chat framing rule found | No official hosted qwen-plus Chat framing rule found | Cookbook-style message formulas are not a billing-exact contract |
| Structured-output overhead | Not proven for current canonical response format | Not proven for hosted API | Text encoding alone does not prove schema/server overhead |
| Unicode behavior | Tokenizer likely supports it, but V4 mapping is unproven | Open-source tokenizers support multilingual text; hosted mapping unproven | `tiktoken` is byte-based and handles Unicode |
| Canonical payload match | Basic OpenAI Chat Completions shape is compatible | Basic OpenAI-compatible shape likely compatible; exact hosted options not established | Current Chat Completions shape is compatible |
| License | Tokenizer archive license not established in reviewed evidence | Exact target tokenizer license/asset not selected | `tiktoken` repository is MIT |
| Dependency size | Unknown until archive is selected | Medium/large if Transformers/model assets are required | Small/medium native wheel |
| Confidence | MEDIUM that protocol works; LOW for exact billing count | MEDIUM for protocol/snapshot; LOW for exact billing count | HIGH for text encoding; LOW for exact Chat/schema billing count |
| Decision | **REJECT FOR LIVE EXACT BUDGET** | **REJECT FOR LIVE EXACT BUDGET** | **REJECT FOR LIVE EXACT BUDGET** |

## DeepSeek A0 follow-up

Owner selected DeepSeek / `deepseek-v4-flash`, but A0 did not approve the
pairing. The official Token Usage link delivered a V3-named Archive with no
V4 mapping or license. Layer A was deterministic for that Archive; Layers
B/C/D remained unverified. DeepSeek remains **REJECT FOR LIVE EXACT BUDGET**
unless new official V4-specific evidence closes every layer.

## Exactness decision

All three candidates may support exact text encoding under some local setup
(layer A). None currently proves exact Chat message framing (B), structured
output/schema overhead (C), and Provider billing tokens (D) for the exact
canonical request. The 4096 hard input ceiling cannot rely on an undocumented
or estimated overhead formula.

No candidate is approved. The owner must first choose the intended Provider
and exact API model id. That decision must then be accompanied by official,
versioned evidence binding the local tokenizer and complete request framing to
that API snapshot.
