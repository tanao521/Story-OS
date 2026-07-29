# Phase 0D4-F-RC1 Delivery Report

## Evidence

- Compile authority: immutable `data/narrative_compile/operations/{operation_id}.json`.
- Commit authority: immutable `data/narrative_compile/commit_operations/{operation_id}.json`.
- Mutable phases are separate `.phase.json` files; durable outcomes are separate `.result.json` files.
- Result scope, canonical request fingerprint, and outcome fingerprint are validated before replay.
- Candidate recovery scans existing VersionManager manual artifacts by candidate fingerprint.
- Commit recovery consumes durable commit results before considering a new ChapterCommitService call.
- Turn lifecycle remains append-only; duplicate included/committed transitions are skipped by journal state.
- Compile performs no Canon, Chroma, or NarrativeMemory writes. Commit uses only ChapterCommitService and the complete VectorScope.

## Fault and concurrency matrix

Compile fault points: 6 (`after_authority_claim`, `after_turn_snapshot`,
`after_candidate_write`, `after_first_included_transition`,
`after_all_included_transitions`, `before_completed_marker`).

Commit fault points: 7 (`after_authority_claim`, `after_candidate_verification`,
`before_chapter_commit`, `after_chapter_commit_success`,
`after_first_committed_transition`, `after_all_committed_transitions`,
`before_completed_marker`).

Concurrency evidence cases: immutable authority race plus the four required
domain scenarios (compile/compile, commit/commit, compile/confirm, and
commit/archive) remain represented by the branch/transition authority tests;
category labels overlap and are not additive.

## Validation log

| Command | Collected | Passed | Failed | Skipped | Exit |
|---|---:|---:|---:|---:|---:|
| `python -m pytest tests/test_phase0d4f_*.py -q` (PowerShell-expanded) | 14 | 14 | 0 | 0 | 0 |
| `python -m pytest tests/test_chapter_commit_service.py -q` | 16 | 16 | 0 | 0 | 0 |
| `python -m pytest tests/test_revision_service.py -q` | 4 | 4 | 0 | 0 | 0 |
| VersionManager/manual/web version tests | 24 | 24 | 0 | 0 | 0 |
| `python -m pytest tests/test_phase0d4d_rc1.py -q` | 22 | 22 | 0 | 0 | 0 |
| `python -m pytest tests/test_phase0d4e_rc.py -q` | 15 | 15 | 0 | 0 | 0 |
| `python -m pytest tests/test_real_data_protection.py -q` | 2 | 2 | 0 | 0 | 0 |
| `python -m pytest tests/test_static_path_guard.py -q` | 3 | 3 | 0 | 0 | 0 |

The literal unexpanded PowerShell command `python -m pytest tests/test_phase0d4f_*.py -q`
collected 0 and exited 1 because PowerShell does not expand pytest globs; the
equivalent expanded command above is the authoritative result. `py_compile`
and `git diff --check` both passed. No Provider, network, Git write, or real
project-data write was used.
