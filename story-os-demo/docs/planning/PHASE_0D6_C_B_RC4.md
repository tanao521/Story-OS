# Phase 0D6-C-B-RC4 — Formal Authority Verification Harness

## Scope

RC4 adds test-only authority evidence. Production frontend, backend, routes,
sealed services, templates, schemas, and configuration remain frozen.

## Formal completion path

`tests/test_phase0d6c_b_rc4_frontend.py` builds an isolated temporary project
and completes its chapter only through the production compiler, review gate,
and `NarrativeChapterCommitService`. It then reads the result back through
`SimulatorLoopStateService`, requiring both `chapter_progression.completed`
and a durable commit identifier. No completed state is hand-written.

## Browser transport controls

The isolated FastAPI fixture now accepts `STORYOS_RC4_READINESS_DELAY` in
addition to the existing start-response delay and response-loss controls. The
ASGI wrapper delays only the already-produced response, preserving the real
route and service behavior while allowing a Chromium race to be reproduced.

## Gate

This harness closes the formal-completion and readiness-delay testability gaps
identified by RC3. It does not itself claim the full two-project/sibling-branch
Chromium matrix; that acceptance remains pending an executed RC4 browser run.
