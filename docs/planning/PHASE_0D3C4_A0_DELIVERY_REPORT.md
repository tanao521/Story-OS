# Phase 0D3C4-A0 Delivery Report

## Final status

**BLOCKED — retain real Profile block; do not enter 0D3C4-A.**

## Required answers

- Archive acquired: yes, from the official Token Usage page's CDN link.
- File: `deepseek_v3_tokenizer.zip`, 1,979,745 bytes.
- SHA-256: `c954ca6f6e54281d72d3c27e2430cea7663f81292b39982e2f97890c66c302de`
  (audit baseline, not an official published checksum).
- Contents: one Python demo, `tokenizer_config.json`, `tokenizer.json`, and
  macOS metadata; no weights, pickle, executable, README, dependency manifest,
  license, checksum, revision manifest, or model allowlist.
- License: unverified; no LICENSE/NOTICE in Archive or reviewed download page.
- Dynamic download: fixed JSON can run offline; official demo asks for
  `transformers` and enables `trust_remote_code=True`. It was not run.
- Windows/Python: Layer-A JSON loading works with the already-installed
  `tokenizers`; official demo dependency was not installed.
- Direct V4 Flash support statement: none.
- V4 Flash/Pro shared tokenizer statement: none.
- Layer A: verified only for this V3 Archive.
- Layer B: unverified.
- Layer C: unverified.
- Layer D: unverified.
- Canonical payload: basic Chat shape matches, but explicit thinking policy and
  actual JSON `response_format` are missing.
- Thinking: DeepSeek V4 defaults enabled; Reader Persona needs a separately
  approved explicit mode rather than relying on that default.
- JSON Output overhead: undocumented and unverified.
- Golden fixtures: Layer-A-only audit values created; no full-request/billing
  claims.
- Production code/dependency changes: none.
- Provider/API/credential calls: none; official Archive download was the only
  allowed network transfer.

## Verification

- 0D3C3 + 0D3C2-RC focused safety tests: **32 passed**.
- `python -m compileall -q .`: **passed**.
- Isolated fixed-JSON tokenizer probe: deterministic across repeated runs;
  socket create/connect canary recorded **0 network attempts** and the isolated
  cache remained empty.
- `pyproject.toml` and `uv.lock`: **unchanged by SHA-256** during A0.
- Real Provider/API/credential/token/cost calls: **0**.
- Real model/panel Runs: **0/0**.
- Real Live ticket/audit/ownership: **0/0/0**.
- Chroma: **6/6 SHA-256 matches**.
- Authority assets: **16/16 SHA-256 matches**.
- Obsidian bindings: **30**.
- Production capability environment: **absent/default-off**.
- Product code and dependencies changed by A0: **none**. A0 changed only the
  required planning, security, and testing evidence documents.

No real Provider test or full-suite claim is made.

## Next decision

Strict policy: remain blocked pending official V4-specific mapping, license,
full framing/JSON overhead, and billed-equality evidence.

Alternative: submit a separate Conservative Budget Policy Owner Decision. It
must explicitly abandon the exact-counter readiness claim and cannot enable
production Live in A0.
