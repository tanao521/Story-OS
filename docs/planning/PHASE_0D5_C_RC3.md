# Phase 0D5-C-RC3 — Durable Completion Before Response Loss

状态：**PASSED**

RC3 used a fixture-only ASGI transport fault (`STORYOS_RC3_DROP_CONFIRM_RESPONSE=1`). The real Confirm route ran to completion first; the wrapper then dropped exactly one HTTP response. No production endpoint or authority was bypassed.

## Verified

- one Confirm POST and one operation authority;
- durable Turn result, branch transition chain, and branch state persisted before the response was dropped;
- browser reload performed only read requests and recovered the same result and Turn identity;
- UI showed `Durable result restored from authoritative state.` and exposed Continue to next turn;
- no second Confirm operation, duplicate result, or duplicate History item;
- fresh browser console remained clean.

The read-model recovery adapter now checks the authoritative TurnStore result path (`data/narrative_turn/results/...`) when the operation authority has no adjacent result artifact. This is the minimal recovery-read fix required by the browser symptom and remains within 0D5-C.

Phase 0D5-D remains not entered.
