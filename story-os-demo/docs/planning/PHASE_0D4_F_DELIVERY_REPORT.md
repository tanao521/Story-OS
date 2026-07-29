# Phase 0D4-F Delivery Report

- Compiler call graph: explicit scope → branch/source validation → Turn journal snapshot → deterministic candidate → VersionWriterFacade → included transitions.
- Commit call graph: candidate/review/freshness validation → ChapterCommitService → existing post-commit chain → committed transitions.
- Ordering authority: `APPLIED_TO_BRANCH` transition sequence, with Turn ID as deterministic tie-breaker.
- Candidate path: existing `data/manual` VersionManager layout and versions index, written by `VersionWriterFacade`.
- Operation authorities: `data/narrative_compile/operations` and `commit_operations`, each with immutable request binding and phase records.
- Review gate: compilation writes `review_status=pending`; commit rejects anything other than explicit approval.
- Safety: no Provider, direct Canon, direct Chroma, or direct NarrativeMemory mutation from compiler/commit orchestration.
- Recovery: same operation/request replays durable candidate/commit artifacts; conflicting reuse fails closed.

Validation performed: `python -m pytest tests/test_phase0d4f_*.py` (9 passed; PowerShell expanded the glob before invocation), `python -m pytest tests/test_phase0d4e_rc.py -q` (15 passed), `python -m pytest tests/test_chapter_commit_service.py tests/test_commit_manual_version.py -q` (18 passed), plus `py_compile` and `git diff --check`.
