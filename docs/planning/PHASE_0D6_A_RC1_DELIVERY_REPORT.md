# Phase 0D6-A-RC1 Delivery Report

## Outcome

Phase 0D6-A-RC1 is **PARTIALLY PASSED**.  The verification found and repaired
two lifecycle defects: pre-action fault markers that could skip publication on
replay, and a filesystem lock that did not provide thread-level exclusivity.

## Changed Files

- `story-os-demo/system/chapter_lifecycle_service.py`
- `story-os-demo/system/revision_service.py`
- `story-os-demo/tests/test_phase0d6a_chapter_lifecycle.py`

## Validation Ledger

| Command | Passed | Failed | Exit |
|---|---:|---:|---:|
| `python -m pytest -q tests\\test_phase0d6a_chapter_lifecycle.py tests\\test_phase0d6a_read_purity.py` | 56 | 0 | 0 |
| 0D5 focused + ChapterCommitService + RevisionService + real-data/static-path guards | 86 | 0 | 0 |

Syntax validation for the four lifecycle modules passed before the focused
suite.  Tests used temporary project roots only.

## Evidence Counts

- Read-purity cases: 14
- Fault-injection cases: 11 (eight-point parameterized matrix plus legacy
  replay coverage)
- Concurrency cases: 2 (including one barrier-synchronised two-thread case)
- Warning cases: 2
- Filesystem/immutability cases: 3 direct previous-chapter checks; broader
  filesystem-boundary matrix remains outstanding

Category labels overlap and are not additive.

## Safety Ledger

- Provider calls: 0
- External network: 0
- Real project writes: 0
- Real data/chroma writes: 0
- Frontend authority and production UI changes: 0
- ChapterCommitService changes: 0
- Candidate/Review authority changes: 0
- New dependencies: 0
- Git write operations: 0

## Seal Decision

The unverified freshness, archive-race, scope-isolation, and full filesystem
boundary requirements prevent sealing Phase 0D6-A.  Phase 0D6-B is not entered.
