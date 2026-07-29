# Phase 0D4-E1-RC1 — Crash-Safe Registry Lock and Lifecycle Recovery

> Status: **PASSED**
>
> E1 status after this release candidate: **SEALED**

RC1 closes the crash-safety and real-concurrency gaps in the E1 Branch
Lifecycle HTTP API. Scope remains limited to branch registry state and its
operation journal.

## Authority model

- `{operation_id}.json` is the immutable operation authority: scope, operation
  kind, expected revision, and canonical request fingerprint only.
- `{operation_id}.phase.json` is the mutable progress authority. Its scope and
  fingerprint are checked against the immutable record on every retry.
- A missing or mismatched phase fails closed unless durable branch/registry
  artifacts prove a safe recovery path; replay uses the same request
  fingerprint and operation ID.

## Lock model

Each project/timeline registry has its own atomic directory lock. The owner
record contains PID and a random nonce. A competing process may reclaim only a
lock whose recorded PID is dead; final cleanup requires the matching PID and
nonce. Windows liveness uses process exit status rather than a signal probe.

## Recovery and concurrency evidence

The fault matrix injects a crash after durable identity publication (create),
registry publication (select), archive mutation, and restore mutation. A clean
retry repairs the phase and a final retry is an idempotent replay. Real process
tests prove one revision winner for competing selects and reclaim a lock after
the owner process is killed. Different timelines retain independent locks.

## Boundaries

Only `data/branches/` and `data/branch_operations/` are written by E1. No
NarrativeMemory migration, retrieval change, Chroma access, Canon write,
Provider call, or Git/remote operation is part of RC1. E2 and E3 remain
**NOT ENTERED / NOT AUTHORIZED**.

## Validation

- E1-RC1 focused suite: **16 passed**.
- D-RC1 and security regression suite: **166 passed**.
- Combined related suite: **548 passed**.
- Python compilation and `git diff --check`: passed.
