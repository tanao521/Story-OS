# Cross-Chapter Progression UI Contract Map

## Entry and call chain

```text
simulator mode + bound context
  -> completion/result progression panel
  -> GET /api/chapter-progression/readiness
  -> render readiness state
  -> explicit READY click
  -> POST /api/chapter-progression/start-turn
  -> validate scope/fingerprints/turn identity
  -> rebind existing narrative-turn workspace
```

The panel belongs inside `#simulator-loop-shell`; Traditional mode must not initialize it, poll it, or issue either request.

## Readiness GET

Request query: `project_id`, `timeline_id` (default `main`), optional `branch_id`, optional `previous_chapter_id`.

Successful route envelope:

```json
{
  "ok": true,
  "message": "",
  "result": {
    "readiness_code": "READY_TO_START_TURN",
    "ready_to_start_turn": true,
    "project_id": "…",
    "timeline_id": "main",
    "branch_id": "…",
    "previous_chapter_id": 1,
    "successor_chapter_id": 2,
    "chapter_lifecycle_operation_id": "…",
    "planning_context_fingerprint": "…",
    "branch_revision": "…",
    "branch_authority_fingerprint": "…",
    "existing_turn_id": null,
    "existing_turn_status": null,
    "blocking_reasons": [],
    "authority_fingerprint": "<64 hex>"
  },
  "warnings": [],
  "errors": []
}
```

The UI stores the result only in in-memory state. The route is `Cache-Control: no-store`.

## Durable start POST

Request body is `ChapterProgressionStartRequest`:

```json
{
  "operation_id": "client-generated-idempotency-key",
  "project_id": "…",
  "timeline_id": "main",
  "branch_id": "…",
  "previous_chapter_id": 1,
  "successor_chapter_id": 2,
  "expected_readiness_fingerprint": "<64 hex>"
}
```

The server re-reads readiness under durable locks, claims the operation, publishes exactly one plan and the initial `PLANNED -> AWAITING_ACTION` transition, then returns a preview-only result. A successful result includes `operation_id`, scope, lifecycle operation ID, `readiness_fingerprint`, `turn_id`, `turn_status`, plan/transition fingerprints, preview, and `completed_at`.

The client must validate that returned scope, successor, operation ID, and readiness fingerprint match the current intent before rebind. It must not confirm the recommended action automatically.

## Operation and fingerprint lifecycle

1. Generate `operation_id` only after an explicit READY click; keep it in memory.
2. Reuse it for a response-loss/network retry of the same unchanged intent.
3. Never place operation IDs or authority fingerprints in URL, localStorage, or user-authored text.
4. Clear the operation intent after terminal success, `OPERATION_CONFLICT`, stale context, or corruption/recovery-required handling.
5. Treat `authority_fingerprint` as a server assertion, not a client-computed value. A mismatch yields stale state and requires a fresh GET.

## Context rebind and recovery

After success, abort superseded requests, update authoritative project/timeline/branch/chapter context, retain only safe IDs in URL state, load the returned `turn_id` through the existing narrative-turn context path, and render `AWAITING_ACTION`. If readiness reports `TURN_ALREADY_STARTED`, skip POST and offer “continue existing Turn” using `existing_turn_id/status`.

Response-loss may retry with the same operation ID while the intent and context are unchanged. `TURN_START_SOURCE_CHANGED` requires a fresh readiness GET. `OPERATION_CONFLICT`, `CORRUPT_OPERATION`, `TURN_START_RECOVERY_REQUIRED`, invalid envelopes, or scope mismatches require a visible recovery/manual-review state; never blind-loop.

## API-error envelope rule

Chapter-progression routes return top-level `errors` codes. Narrative Turn routes use a different nested error wire shape. The progression UI must parse the former and preserve raw codes for diagnostics.

