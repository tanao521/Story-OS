# Phase 0D5-D-RC1 — Reject, Recovery, Navigation, Isolation Closure

Status: PASSED. Phase 0D5-D2 and Phase 0D5-D are SEALED. Phase 0D5-RC is
AUTHORIZED but implementation is not entered.

## Accepted normal path

The production-shaped temporary fixture contains two durable confirmed Turns.
Real Chromium verified Compile → pending Candidate → authoritative Approve →
visible Commit control → accessible Commit dialog → Commit → authoritative
Chapter Completion. The previously accepted evidence remains unchanged.

## Remaining matrix

| Scenario | Result | Durable/network evidence |
| --- | --- | --- |
| Reject blocks Commit | PASS | Compile 1, Review 1, Commit 0; decision/review status rejected; candidate and source bytes unchanged; Commit hidden/disabled after refresh |
| Compile response-loss | PASS | Compile POST 1; response dropped after durable completion; recovery read restored the same pending Candidate; no second Compile |
| Review response-loss | PASS | Review POST 1; approved decision durable before response drop; recovery read restored approved state and Commit visibility; no second Review |
| Commit response-loss | PASS | Commit POST 1; ChapterCommitService/Canon completion durable before response drop; recovery read restored same commit and Completion; can_commit=false |
| Refresh / Back-Forward | PASS | Candidate and Completion views restored; History → Candidate and Candidate → Complete back/forward changed only URL/view; mutation counts unchanged |
| Scope isolation | PASS | Cross-Branch and Cross-Chapter candidate URLs failed closed, removed candidate_id, showed no candidate content, and left controls disabled |
| Traditional Mode smoke | PASS | Traditional mode remained selected; Simulator shell hidden; editor and traditional review surface remained available; simulator candidate/view parameters were absent |

All response faults were one-shot, fixture-only ASGI transport interruptions.
They were applied after the existing route/service completed and never added to
production DTOs, endpoints, or authority services.

## Safety boundary

Provider calls, external network calls from Story OS, direct frontend Canon or
Chroma calls, alternative Commit routes, new Candidate/Review/Commit authority,
real project writes, dependencies, and Git write operations: 0.
