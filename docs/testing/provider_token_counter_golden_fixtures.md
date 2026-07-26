# Provider Token Counter Golden Fixtures

0D3C3 uses `FixtureJsonByteCounter` only for the in-process fixture provider.
Its defined token is one byte of canonical, sorted, compact UTF-8 JSON, making
the expected values exact for that test protocol. It is deliberately not an
OpenAI/DeepSeek tokenizer and cannot make a real profile ready.

| Fixture | Exact fixture tokens |
| --- | ---: |
| empty system / short user | 154 |
| Chinese | 156 |
| English punctuation and newline | 189 |
| mixed Chinese/English/Unicode | 178 |
| long repeated chapter excerpt | 2563 |
| JSON response format | 200 |

Tests also cover deterministic repeated count, unknown model, counter revision,
canonical envelope equality, prompt/schema fingerprint changes, exact payload
handoff to the adapter, dry-run over-budget rejection, counter exception,
network canary, redacted public readiness, and zero Provider calls when the
budget Gate blocks.
