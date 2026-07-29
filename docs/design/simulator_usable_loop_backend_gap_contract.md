# Simulator Usable Loop Backend Gap Contract (0D5-A)

This document classifies design needs against the routes and DTOs read during 0D5-A. It does not add APIs.

| Need | Classification | 0D5-B implication |
|---|---|---|
| Existing context/plan/feasibility/preview/confirm | EXISTING_API_CAN_SUPPORT | aggregate into loop status and next-turn response |
| Turn History read model | REQUIRES_READ_AGGREGATION | expose immutable sequence, lifecycle, evidence, candidate/commit links |
| Current loop/session status | REQUIRES_READ_AGGREGATION | resolve unfinished Turn/Candidate/commit recovery on entry |
| Candidate list/detail aggregation | REQUIRES_READ_AGGREGATION | scope list by project/timeline/branch/chapter |
| Durable Candidate approval | IMPLEMENTED_IN_0D5_D1 | independent immutable review authority; first-writer-wins, replay/recovery, chain validation, and pending/rejected/stale/superseded candidates remain non-committable |
| Branch readiness / registry revision | REQUIRES_READ_AGGREGATION | expose lifecycle, vector readiness, active pointer, rebuilding state |
| Chapter progression status | REQUIRES_READ_AGGREGATION | completion result and explicit next-chapter scope |
| Recovery result aggregation | REQUIRES_READ_AGGREGATION | map durable operation result to user-safe status |
| New UI intents | DESIGN_ONLY | route through existing authorities; no client mutation shadow |

## Explicit non-inferences

No frontend-only approval, commit shortcut, hidden branch selection, automatic chapter creation, direct Canon/Chroma write, or provider/live execution is permitted. If a desired screen cannot be supported by the listed routes and durable artifacts, it remains a documented gap rather than an invented contract.
