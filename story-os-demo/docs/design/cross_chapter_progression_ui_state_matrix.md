# Cross-Chapter Progression UI State Matrix

| UI state | Entry condition | Allowed work | Primary user treatment | Exit |
|---|---|---|---|---|
| `UNAVAILABLE` | no simulator context, invalid project/chapter, unsupported timeline, or no active branch | none | explain required context; no request | valid simulator context |
| `LOADING_READINESS` | readiness GET in flight | abort prior request; generation-guard response | busy status, no action | fresh response or error |
| `BLOCKED` | `ready_to_start_turn=false` | display blocking reasons only | disabled primary action; accessible reason | context/authority changes |
| `READY` | `READY_TO_START_TURN` | await one explicit click | enabled “Start next chapter initial Turn” | click, context change, stale response |
| `STARTING` | POST in flight | one request; same op ID on response-loss retry | disable button, `aria-live` progress | success, mapped error, retry |
| `STARTED` | valid durable-start result | rebind and load returned Turn | show Turn ID/status and next action UI; never auto-confirm | existing Turn view |
| `EXISTING_TURN` | `TURN_ALREADY_STARTED` with one valid existing turn | GET/load existing Turn | offer continue; never POST | context change or load result |
| `STALE` | fingerprint, scope, or context mismatch; `TURN_START_SOURCE_CHANGED` | discard old response/intent and GET again | explain that readiness changed; no auto-start | fresh readiness response |
| `RECOVERY_REQUIRED` | `TURN_START_RECOVERY_REQUIRED` or other recoverable durable uncertainty | manual review/reload path only | preserve operation ID in diagnostic memory until decision; no blind retry | explicit retry after fresh readiness or operator resolution |
| `CORRUPT` | `CORRUPT_OPERATION`, `BLOCKED_CORRUPT_AUTHORITY`, `BLOCKED_EXISTING_TURN_CORRUPT`, invalid response | none beyond diagnostics | stop mutation and expose recovery guidance | manual resolution/new context |
| `NETWORK_OR_ROUTE_ERROR` | network failure, abort not caused by context change, non-JSON, 5xx | bounded retry with same intent/op ID | retry button and clear status | retry, fresh GET, or recovery |

## Browser and acceptance matrix (for C-FV)

| Scenario | Expected result |
|---|---|
| simulator context loads | one readiness GET, panel renders; no POST |
| Traditional mode selected | panel hidden; no readiness/start requests |
| blocked readiness | clear blocking reason, disabled action, no POST |
| ready + keyboard activation | one POST, button locks, one operation ID |
| double click / repeated Enter | still one durable operation; no duplicate Turn |
| lost POST response | same operation ID retry replays the durable result |
| changed fingerprint | `STALE`, fresh GET, no automatic start |
| `TURN_ALREADY_STARTED` | existing Turn is loaded; POST is skipped |
| corrupt/recovery code | mutation stops and recovery guidance is focusable |
| context switch/back-forward during GET | stale response ignored; current context wins |
| success rebind | returned Turn is visible in `AWAITING_ACTION`; no auto-confirm |
| 320px viewport + keyboard | no horizontal overflow; focus and live status remain usable |

## Error-code mapping

| Backend code | UI mapping | Retry rule |
|---|---|---|
| `OPERATION_CONFLICT` | `CORRUPT`/manual review | no reuse of that operation ID |
| `TURN_START_SOURCE_CHANGED` | `STALE` | fresh readiness GET |
| `TURN_ALREADY_STARTED` | `EXISTING_TURN` | no POST |
| `BLOCKED_LIFECYCLE_INCOMPLETE`, `BLOCKED_LIFECYCLE_CONFLICT`, `BLOCKED_TIMELINE_UNSUPPORTED`, `BLOCKED_BRANCH_ARCHIVED`, other `BLOCKED_*` | `BLOCKED` | context/authority change only |
| `BLOCKED_CORRUPT_AUTHORITY`, `BLOCKED_EXISTING_TURN_CORRUPT` | `CORRUPT` | manual resolution |
| `CORRUPT_OPERATION` | `CORRUPT` | manual resolution; do not loop |
| `TURN_START_RECOVERY_REQUIRED` | `RECOVERY_REQUIRED` | only after explicit recovery decision |
| route/network/5xx | `NETWORK_OR_ROUTE_ERROR` | bounded same-intent retry, then fresh GET |

## Interaction and accessibility contract

- 320–480px widths: panel stacks, primary action is full width, no horizontal scrolling.
- Status and error summaries use `aria-live`; disabled controls use `aria-describedby` with the blocking reason.
- Keyboard activation must be equivalent to pointer activation; double activation cannot create two operations.
- On success focus the new Turn heading; on failure focus the error summary.
- Never communicate state by color alone; support reduced-motion preferences and avoid hover-only explanations.
- URL history/back-forward may restore safe context IDs, but must trigger a fresh readiness GET and must not replay a start.
