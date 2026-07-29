# Phase 0D4-E1-RC2 — Final Multi-Process Concurrency and Recovery Closure

> Status: **PASSED**
>
> Phase 0D4-E1: **SEALED**

RC2 closes the remaining E1 evidence gaps without expanding the Branch API
scope. It uses independent operating-system processes for every concurrency
scenario and keeps E2/E3 unauthorized.

## Real-process matrix

- Competing selects on one revision: exactly one winner; the registry journal
  remains continuous and the active pointer is open.
- Select versus active archive: one registry mutation wins; the active pointer
  never references archived A; B/C remain valid.
- Competing active archives: one replacement wins and becomes active; the
  losing replacement remains open/inactive; A has one archive transition.
- Restore versus select: restore opens B without selecting it; select may make C
  active; lifecycle and activity remain separate.
- Killed lock owner: PID, nonce, and process-start identity are recorded; a
  dead owner is reclaimed and a new owner is published.
- Different timelines: independent lock authorities permit both registry
  chains to progress.

## Recovery matrix

Fault-injection cases cover operation claim, durable identity/registry/lifecycle
publication, and the completion-marker boundary for create, select, archive,
and restore. Every retry uses a new service instance and the same operation ID.
The tests verify authority bytes remain unchanged, phase scope/fingerprint
checks fail closed, missing phases are reconstructed from durable artifacts,
exactly one lifecycle transition is present, the active pointer is open, and a
second retry is an idempotent replay.

## Boundaries

Only `data/branches/` and `data/branch_operations/` are written. No
NarrativeMemory, retrieval, Chroma, Canon, Provider, browser, Git, or remote
operation was performed. E2 and E3 remain **NOT ENTERED / NOT AUTHORIZED**.
