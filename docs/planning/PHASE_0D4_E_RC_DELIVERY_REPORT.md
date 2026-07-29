# Phase 0D4-E-RC Delivery Report

## Verdict

**PASSED.** Phase 0D4-E3 is sealed and Phase 0D4-E is sealed. Phase 0D4-F was
not entered.

## Changes made for acceptance defects

- Branch manifests now carry readiness and an integrity fingerprint; retrieval
  validates manifest scope/readiness/fingerprint before querying Chroma.
- Scoped metadata now includes `source_identity`.
- Operation authority uses a real source-manifest fingerprint; phase files bind
  the full scope and canonical request fingerprint. Eight recovery fault points
  are exercised with immutable-authority replay.
- Windows client shutdown explicitly stops Chroma's internal system and clears
  its cache, releasing the SQLite handle after client close.
- Normal NarrativeMemory reads of a non-active branch fail closed once an
  active branch exists; administrative reads remain explicit.
- Missing commit scope produces an explicit `VECTOR_SCOPE_REQUIRED` warning
  without writing a branchless index. Story QA never falls back from a failed
  scoped query to a branchless vector report.
- Vector initialization responses use `Cache-Control: no-store`, preserve the
  complete submitted scope for the queued job, and return a safe missing-scope
  envelope.

## Validation

| Command | Collected | Passed | Failed | Skipped | Warnings | Exit |
|---|---:|---:|---:|---:|---:|---:|
| `python -m pytest tests/test_phase0d4e_rc.py -q` | 15 | 15 | 0 | 0 | 0 | 0 |
| affected callers: commit/revision/QA/context/repair/clone/Web + E2 concurrency/routes | 46 | 46 | 0 | 0 | 0 | 0 |
| integrated E1/E2/E3/E-RC + vector recovery + D-RC1 + real-data/path guard | 132 | 132 | 0 | 0 | 0 | 0 |

The integrated command explicitly enumerated the `test_phase0d4e1_*`,
`test_phase0d4e2_*`, and `test_phase0d4e3_*` files because PowerShell does not
expand pytest globs. Category labels overlap and are not additive.

Executed commands:

```powershell
python -m pytest tests/test_phase0d4e_rc.py -q
python -m pytest tests/test_chapter_commit_service.py tests/test_revision_service.py tests/test_story_qa.py tests/test_context_assembly_service.py tests/test_memory_repair_service.py tests/test_memory_repair_contract.py tests/test_phase0c2_project_clone.py tests/test_web_api_contract.py -q
$testFiles = @((Resolve-Path tests/test_phase0d4e_rc.py)) + @(Get-ChildItem tests -Filter 'test_phase0d4e1_*.py' | ForEach-Object FullName) + @(Get-ChildItem tests -Filter 'test_phase0d4e2_*.py' | ForEach-Object FullName) + @(Get-ChildItem tests -Filter 'test_phase0d4e3_*.py' | ForEach-Object FullName) + @((Resolve-Path tests/test_phase0c1_vector_isolation.py), (Resolve-Path tests/test_phase0c1_recovery.py), (Resolve-Path tests/test_phase0d4d_rc1.py), (Resolve-Path tests/test_real_data_protection.py), (Resolve-Path tests/test_static_path_guard.py)); python -m pytest $testFiles -q
```

### Category coverage

- Metadata/ID and server-side query isolation: E3 plus E-RC scoped-query tests.
- Caller propagation, HTTP/job envelope, and legacy guard: E-RC plus affected
  caller suite.
- Archive/restore/readiness and Memory isolation: E1/E2/E-RC tests.
- Recovery fault matrix: eight injected E-RC fault points with same-ID replay.
- Windows client lifecycle: real Chroma 1.5.9 on `win32`; temp-root deletion
  passed, with no mock substituted for this check.
- Filesystem isolation: temporary roots only; tests verify branch memory is not
  rewritten while selecting branches and vector writes remain under temporary
  `data/chroma/`.

## Static guard report

- Files scanned: all production `system/*.py`, `web/*.py`, and `commands.py`.
- Patterns: `from system.vector_memory import`, `import system.vector_memory`,
  and `vector_memory.` qualified calls.
- Production matches: 0.
- `PersistentClient` allowlist: `vector_client_manager.py` (managed runtime
  owner) and `vector_memory.py` (isolated compatibility only).
- No allowlist hides a production caller; the guard scans files individually.

## Safety

No Provider, network, real-project Chroma, Canon bypass, uncommitted Turn
indexing, dependency change, or Git write occurred.
