# Phase 0D6-B-RC1 — Lifecycle Association & Durable Start Recovery

## Goal and Root Cause

The pre-RC1 implementation found a lifecycle outcome by sorting matching
records and treated the first record as authority. That allowed an injected
second bundle, including one for the same successor, to be silently selected.
It also had replay and archive checks that were not strict enough about a
fully durable initial-Turn terminal bundle.

RC1 makes lifecycle association an explicit read-only validation step and
makes initial-Turn start recoverable only from a complete, internally
consistent operation bundle.

## Lifecycle Association Contract

For the requested previous Chapter, readiness reads the sealed lifecycle
resolver first, then accepts exactly one completed `claim + phase + result`
bundle whose scope, request fingerprint, operation type, result fingerprint,
and resolved successor all agree. Basenames are used only to associate the
three immutable files; basename ordering never chooses a winner.

| Evidence condition | Readiness result |
| --- | --- |
| Exactly one matching completed bundle | may continue to authority/freshness checks |
| Two or more matching completed bundles | `BLOCKED_LIFECYCLE_CONFLICT` |
| Missing or incomplete lifecycle evidence | `BLOCKED_LIFECYCLE_*` |
| Malformed, orphan, or internally inconsistent evidence | `BLOCKED_CORRUPT_AUTHORITY` |
| Resolver successor differs from bundle successor | blocked; no turn start |

Readiness also compares the lifecycle claim's completion, branch, and
planning authority to current authoritative data. Any drift returns a
specific blocking code and performs no writes.

## Initial-Turn Start and Recovery

The start bundle is immutable and phase-driven. The durable order is:

1. operation claim;
2. initial plan;
3. `plan_published` phase;
4. first `planned -> awaiting_action` transition;
5. transition phase including its fingerprint;
6. result including plan and transition fingerprints;
7. result phase, then `completed`.

Replay validates the claim, phase, result, plan, and first transition before
returning success. A plan effect written before its phase is recovered without
creating another plan. A result without a completed phase is repaired only if
the complete terminal bundle validates. Any tampering or split-brain evidence
returns `CORRUPT_OPERATION`/recovery-required rather than guessing.

The same component-local `initial-turn` atomic lock is acquired by both the
progression start service and the Narrative Turn confirmation entry point,
scoped by project/timeline/Branch/successor Chapter. This serializes competing
initial-plan writers without introducing a second durable store.

## Archive and Filesystem Safety

Branch archive now validates the terminal start bundle rather than accepting a
result file alone. An incomplete or corrupt operation blocks archive with the
existing safe recovery error. Readiness remains read-only. A successful start
is limited to its three operation files, one plan, and its initial transition;
temporary lock directories are removed after the operation.

## Non-Goals

- The sealed Chapter lifecycle resolver and publication semantics are unchanged.
- No action confirmation, candidate/commit/canon/chroma/Obsidian/provider/UI
  work, or non-main timeline successor is introduced.
- No second lifecycle or Narrative Turn store is created.

