# Phase 0D6-B-RC4

## Outcome

**PASSED — READY FOR OWNER SEAL**

RC4 closed the five RC3 uncertain rows. One compatibility regression was
confirmed and fixed minimally; the remaining four rows are proven unrelated or
environment/shared-state sensitive. No 0D6-B authority regression remains.

## 0D4-D root cause and fix

With RC1's component-local `initial-turn` lock, the losing service observed the
winner's projected state, rebuilt a new plan, and failed action lookup before
immutable-result arbitration. The old contract requires the durable confirmed
fact to win precedence and return `NARRATIVE_TURN_ALREADY_CONFIRMED`.

The minimal fix in `system/narrative_turn_service.py` checks the branch state's
`last_turn_id`, loads its durable result, verifies the same chapter, and returns
`TURN_ALREADY_CONFIRMED` for a different operation before action validation.
Same-operation replay, exactly-once result publication, and the lock remain
unchanged.

## Other four rows

- 0D4-E2 memory concurrency: standalone 5/5 and 0D4-D combination 3/3 pass.
  One failure occurred in a 263-test aggregate as a registry-lock timeout;
  complete-file reruns pass 2/2. This is B (shared-state-sensitive), not D.
- Recovered narrative endpoints return intentional `410 LEGACY_MEMORY_MUTATION_DISABLED`
  under the existing 0D4-E3 legacy guard. Both failures are A/unrelated.
- State-write warning test never reaches the mocked legacy vector update path;
  this is the pre-existing scoped-vector compatibility path, A/unrelated.

## Gates and safety

- 0D6-B focused: 71 passed.
- RC4 narrative/branch targeted files: 23 passed.
- 0D6-A and associated evidence remains green; the expanded current association
  run produced 262 passed and one documented B-class lock timeout.
- 0D5 targeted set: 61 passed; prior full 105-pass gate remains unchanged.
- Final broad: 2283/50/7, exit 1; RC3→RC4 diff is intersection 50, RC3-only 2,
  RC4-only 0.
- `py_compile` and `git diff --check`: passed (existing CRLF warnings only).

RC4 changed one production file and these planning documents only. Provider,
network, token/API, real project/data, Chroma, Obsidian, UI, dependencies,
ChapterLifecycleService, ChapterCommitService, candidate/review authority, and
Git writes: zero.

Phase 0D6-A remains sealed. Owner seal is recommended for 0D6-B; no automatic
seal or next-phase implementation was performed.
