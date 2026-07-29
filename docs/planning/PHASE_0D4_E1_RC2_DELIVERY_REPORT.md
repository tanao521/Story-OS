# Phase 0D4-E1-RC2 Delivery Report

## Final result

**Phase 0D4-E1-RC2: PASSED**  
**Phase 0D4-E1: SEALED**

RC2 adds final real-process concurrency evidence, closes the complete recovery
fault matrix, and closes evidence arithmetic.

## Commands and results

### Focused E1-RC2

```text
python -m pytest tests/test_phase0d4e1_branch_routes.py tests/test_phase0d4e1_branch_operations.py tests/test_phase0d4e1_branch_concurrency.py tests/test_phase0d4e1_branch_recovery.py tests/test_phase0d4e1_branch_process.py tests/test_phase0d4e1_frontend_contract.py -q
collected: 33
passed: 33
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Limited regression/security

```text
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py tests/test_phase0d4d_rc1.py tests/test_phase0d4d_filesystem_diff.py tests/test_real_data_protection.py tests/test_static_path_guard.py -q
collected: 166
passed: 166
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Combined related command

The full related command is the limited regression files plus the E1 route,
operation, concurrency, recovery, process, frontend, and existing 0D4-B/C/D
files listed in the RC1 report. It was run as one command:

```text
collected: 565
passed: 565
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

Category labels overlap and are not additive: real multi-process cases 7;
fault-injection parameter cases 16; route cases 4; authority cases 7;
filesystem-boundary cases are covered by the 166-test limited regression set.

Compileall and `git diff --check` passed. No RC2 browser run was needed because
the UI was unchanged; no RC2 test server was started.

## Artifact invariants

- Authority `{operation_id}.json` is unchanged after replay and recovery.
- Mutable `{operation_id}.phase.json` is the only phase authority.
- Phase scope/fingerprint mismatch fails closed.
- Registry event filenames are continuous and the projection rebuilds from the
  journal.
- Active pointers always reference open branches.
- Temporary fixture writes remain limited to `data/branches/` and
  `data/branch_operations/`.

## Final gate

E1 is sealed. NarrativeMemory migration, retrieval changes, Chroma mutation,
Canon writes, Provider calls, Git writes, and E2/E3 are not entered.
