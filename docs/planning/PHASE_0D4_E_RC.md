# Phase 0D4-E-RC — Integrated Branch Lifecycle, NarrativeMemory and Vector Acceptance

> Status: **PASSED**
>
> Phase 0D4-F: **NOT ENTERED / NOT AUTHORIZED**

## Result

Phase 0D4-E-RC seals the integrated branch lifecycle, NarrativeMemory, and
vector-retrieval authority boundary. This was an acceptance and defect-closure
phase: it added no product capability and did not enter chapter compilation.

## Vector authority and retrieval

Every scoped vector record now carries `project_id`, `timeline_id`,
`branch_id`, `canon_revision_id`, `canon_status`,
`branch_lifecycle_status`, `source_type`, `source_identity`,
`source_fingerprint`, and a record fingerprint. Scoped IDs hash all four
authority dimensions plus source identity and chunk position.

Business retrieval submits this actual server-side Chroma filter before any
application filtering:

```json
{
  "$and": [
    {"project_id": "<project>"},
    {"timeline_id": "<timeline>"},
    {"branch_id": "<branch>"},
    {"canon_revision_id": "<canon-revision>"},
    {"canon_status": "active"},
    {"branch_lifecycle_status": "open"}
  ]
}
```

The application then verifies every returned metadata row against the same
scope. A missing scope, branchless record, scope mismatch, inactive branch,
archived branch, invalid manifest, or non-ready manifest fails closed.

## Caller authority matrix

| Caller | Scope source | Missing scope behavior | Lifecycle check |
|---|---|---|---|
| Context builder / assembly | Explicit `VectorScope` injection | No vector retrieval | `search_scoped` active + open |
| Story QA | Explicit `vector_scope` | No vector/report fallback | `search_scoped` active + open |
| ChapterCommitService | Explicit `vector_scope` argument | `VECTOR_SCOPE_REQUIRED` warning; no write | `index_scoped_records` open |
| RevisionService | Explicit `vector_scope` matching new Canon ID | `VECTOR_SCOPE_REQUIRED` warning; no write | `index_scoped_records` open |
| Memory repair | Explicit scope parameters | `VECTOR_SCOPE_REQUIRED` result | `index_scoped_records` open |
| Web initialization / queued job | HTTP payload copied unchanged into job | `VECTOR_SCOPE_REQUIRED` envelope | Repair indexing validates open |
| `index-vault` CLI | Explicit scope arguments | `VECTOR_SCOPE_REQUIRED` result | Repair indexing validates open |
| Project clone | No selected branch/Canon authority | Explicit `VECTOR_SCOPE_REQUIRED` warning; no rebuild | No branchless fallback |

## Lifecycle and NarrativeMemory

The active branch is the only normal NarrativeMemory read target once an
active branch exists. Inactive and archived branch reads require explicit
administrative mode; archived branch mutation remains rejected. Selecting a
new active branch changes visibility without copying or rewriting the other
branch's memory or vectors. Archive blocks business retrieval immediately from
the lifecycle registry; restore leaves the vector manifest not-ready until an
explicit rebuild completes.

## Vector operation recovery

Authority is immutable at:

```text
data/chroma/operations/{operation_id}.json
data/chroma/operations/{operation_id}.phase.json
```

Authority contains the operation ID/type, complete scope, source-manifest
fingerprint, canonical request fingerprint, and immutable record fingerprint.
The phase record repeats scope and request authority, so a phase mismatch fails
closed. Recovery tests inject faults after authority claim, source scan, old
scope stale marking, first/all record batches, manifest publication,
verification, and immediately before completion. Same-ID retries preserve the
authority bytes, avoid duplicates, verify the manifest, and finish with a
single `COMPLETED` phase.

## Legacy boundary

The static guard scans every production `system/*.py`, `web/*.py`, and
`commands.py` file. Patterns are imports of `system.vector_memory` and
qualified `vector_memory.` calls. There are zero production matches. The only
allowlisted `PersistentClient` owners are `system/vector_client_manager.py`
and retained compatibility module `system/vector_memory.py`; the latter has no
production caller. Direct collection mutation remains confined to vector
lifecycle/compatibility ownership.

## Windows client lifecycle

On Windows with Chroma 1.5.9, acceptance uses a temporary ProjectRoot only:
create, index A/B, query, close, reopen, close, release the last collection
reference, and delete the full temporary ProjectRoot. `VectorClientManager`
now closes the public client, stops Chroma's internal system, and clears its
process cache. Temporary-root deletion succeeds; no real-project Chroma path
is opened or written.

## Boundaries retained

- Provider calls: 0; external network: 0; new dependencies: 0.
- Direct Canon writes, ChapterCommit bypass, RevisionService bypass, and
  uncommitted Turn indexing: 0.
- Real-project Chroma writes and Git write operations: 0.
- Phase 0D4-F was not entered.
