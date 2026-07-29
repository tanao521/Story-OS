# Phase 0D4-E3 — Branch-Aware Vector Isolation

> Status: **PASSED**
>
> Phase 0D4-E-RC: **NOT ENTERED / NOT AUTHORIZED**

E3 introduces immutable `VectorScope(project_id, timeline_id, branch_id,
canon_revision_id)`, branch-aware document IDs and metadata, branch manifests,
and strict lifecycle operations. Business retrieval requires the requested
branch to be both open and active.

Chroma queries use a server-side `$and` filter over project, timeline, branch,
Canon revision, Canon status, and branch lifecycle status. Returned metadata is
then verified again by the application. Branchless legacy records therefore
cannot enter a scoped result even if they share chapter text or source IDs.

Branch manifests live at
`data/chroma/manifests/{timeline_id}/{branch_id}.json`. Recoverable sync
authority lives under `data/chroma/operations/`. Archive removes only the
target branch scope; restore/rebuild produces a fresh manifest before vector
readiness is reported.

Context assembly and Story QA no longer perform branchless legacy retrieval.
Memory repair, ChapterCommit, and Revision indexing require an explicit scope
or fail closed/skip with `VECTOR_SCOPE_REQUIRED`.

The Web initialization endpoint and its queued job carry the complete scope
unchanged. The legacy `index-vault` command now fails closed without a complete
scope. Project cloning does not rebuild a vector index until the clone has an
explicitly selected open branch and active Canon revision.
