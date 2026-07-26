# DeepSeek V4 Tokenizer Supply-Chain Audit

Audit date: 2026-07-23.

## Acquisition

- Official source page:
  https://api-docs.deepseek.com/quick_start/token_usage/
- Official linked asset:
  https://cdn.deepseek.com/api-docs/deepseek_v3_tokenizer.zip
- HTTP result: 200, no redirect observed by `curl`
- Content type: `application/zip`
- File name: `deepseek_v3_tokenizer.zip`
- Size: 1,979,745 bytes
- Download SHA-256:
  `c954ca6f6e54281d72d3c27e2430cea7663f81292b39982e2f97890c66c302de`
- ETag: `69c3d88829e9fec6a98ac6a43dcd14ac`
- Last-Modified: 2025-06-30 04:07:16 GMT

The SHA-256 above is this audit's first-download baseline. DeepSeek did not
publish it as an official checksum on the reviewed page.

## Static archive inventory

The ZIP has ten entries, no absolute/traversal paths, and one functional
top-level directory:

- `deepseek_v3_tokenizer/deepseek_tokenizer.py`
- `deepseek_v3_tokenizer/tokenizer_config.json`
- `deepseek_v3_tokenizer/tokenizer.json`
- `.DS_Store` and `__MACOSX` metadata counterparts

There are no model weights, pickle files, shared libraries, executables,
shell/batch/PowerShell scripts, dependency manifests, README, LICENSE, NOTICE,
official checksum, version manifest, or model-id allowlist.

`tokenizer.json` is a fixed BPE asset with 128,000 vocabulary entries and 818
added tokens. `tokenizer_config.json` identifies `LlamaTokenizerFast`, includes
a Jinja chat template, and declares a 16,384 model maximum. Neither JSON file
mentions V4, V4 Flash, V4 Pro, `deepseek-v4-flash`, or
`deepseek-v4-pro`.

## Script audit

The 277-byte Python demo instructs the user to install `transformers`, then
calls:

```python
transformers.AutoTokenizer.from_pretrained("./", trust_remote_code=True)
```

It encodes only `"Hello!"`. The script:

- does not accept a model id;
- does not construct Chat Completions messages;
- does not handle `response_format`;
- does not compute billed request tokens;
- requires an uninstalled dependency;
- enables remote-code trust even though the supplied path is local.

The script was not executed. Installing its dependency and executing
`trust_remote_code=True` are outside A0 authorization.

## License and runtime decision

No license file or license statement exists in the Archive. The official
webpage does not bind an Archive license in the reviewed content. Therefore
license acceptability is **UNVERIFIED**.

The fixed JSON can be loaded on Windows by the already-installed
`tokenizers` package without network. That proves only local text encoding for
this specific Archive. The official demo's stated execution route requires
`transformers`, which is not installed and was not added.

Supply-chain verdict: **insufficient for production integration**. The Archive
is official and statically inspectable, but it is explicitly V3-named, lacks a
license/revision/V4 mapping, and its demo does not address full API requests.

