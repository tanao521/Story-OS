# Live Execution Recovery Semantics

| State | Meaning | Provider retry |
| --- | --- | --- |
| `issued` | immutable consent exists; no ownership | none |
| `in_progress` | atomic ownership exists before provider work | none |
| `completed` / `partially_completed` | immutable Panel Run returned | none |
| `failed` / `blocked` | immutable result/error recorded | none |
| `expired` | consent passed its expiry before ownership | none |
| `cancelled` | cancelled before provider ownership | none |
| `cancel_requested` | request recorded after work may have started; remote cancellation is not claimed | none |
| `reconciliation_required` | provider outcome cannot be safely known after interruption/stale in-progress | none |
| `rejected` | ticket/key/profile/source/scope validation failed | none |

Browser navigation or response loss is not server cancellation. Recovery reads
the ticket-bound ownership record and returns a safe status. It never creates a
new Run, replays a provider request, or falls back to another provider.

Source is bound to consent fingerprints. The service re-plans before ownership;
a changed source blocks with `SOURCE_CHANGED_AFTER_CONSENT`. Each child request
also revalidates those fingerprints immediately before its provider call. If a
source changes during a sequential panel, later children are blocked and no new
source is read for them; the Panel is partial/blocked and cannot be reviewed as
current.
