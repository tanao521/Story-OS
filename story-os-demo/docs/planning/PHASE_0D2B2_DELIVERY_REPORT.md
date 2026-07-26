# Phase 0D2B2 Delivery Report

Verification is completed only after the final regression and integrity checks
recorded at the end of this file. This report distinguishes implemented design
from verification evidence and does not claim real-provider acceptance: all
automated tests use local deterministic fakes or mock mode.

## Implemented controls

- Bounded multi-Persona request and read-only plan contract.
- Deterministic ID ordering, server-side five-Persona ceiling, and explicit
  live authorization/budget gate.
- Sequential reuse of the existing single-Persona execution service.
- Immutable project-local panel records with separated authoritative/model data.
- Correct cache, usage, partial-completion, invalid-output, and staleness
  semantics.
- CLI and Web API routes with sensitive request fields rejected.

## Verification

All tests were run with the workspace virtual environment, `PYTHONUTF8=1`, and
`PYTHONPYCACHEPREFIX=D:\\novel\\StoryOS\\pycache_0d2b2`. The UTF-8 setting is
required for Windows subprocess tests that would otherwise decode UTF-8 CLI
output with GBK.

- Focused Phase 0D2B2 suite: 13 passed.
- Related Phase 0D suites: 239 passed (0D1: 51; 0D2A: 63; 0D2B1 live-provider:
  51; 0D2B1 model-persona execution: 74).
- Related Phase 0C3 suite: 161 passed.
- Repository collection: 1263 tests collected.
- Repository regression: seven non-overlapping sorted test-file batches covered
  all collected tests: 1258 passed, 5 skipped, 0 failed, 0 errors.
- `python -m compileall .`: passed.
- Chroma integrity: all six files match the RC3-IBR baseline by SHA-256, byte
  size, and nanosecond mtime.
- Authority source assets: all 16 baseline assets match by SHA-256 and size;
  expected asset-set hash is
  `4fd10deda7ce1f5baa7d26a401488167356059b4d90125e8312b11b475a6689c`.
- Obsidian binding count remains 30. The test configuration uses temporary
  projects and local fakes/mock mode; no real provider token was configured or
  exercised.

## Seal decision

**PASSED — Phase 0D2B2 is sealed.** The pre-existing RC3-IBR Chroma baseline
was recovered from the local Codex session archive and independently rechecked
after this phase. No protected Chroma or authority-source asset changed during
the validation run.
