# Phase 0D4-E2 — Branch-Aware NarrativeMemory Schema and Copy-Only Migration

> Status: **SEALED** (RC1)
>
> Phase 0D4-E3: **NOT ENTERED / NOT AUTHORIZED**

E2 adds an explicit branch-scoped NarrativeMemory service while preserving the
legacy flat API as compatibility behavior. New branch-aware operations require
`project_id`, `timeline_id`, and `branch_id`; Canon-bound records additionally
carry `canon_revision_id`.

## Branch-aware paths

```text
data/narrative_memory/events/{timeline_id}/{branch_id}/chapter_{n}.json
data/narrative_memory/state/{timeline_id}/{branch_id}/current.json
data/narrative_memory/snapshots/{timeline_id}/{branch_id}/chapter_{n}.json
data/narrative_memory/overrides/{timeline_id}/{branch_id}/...
data/narrative_memory/retrieval/{timeline_id}/{branch_id}/history.json
data/narrative_memory/migrations/{operation_id}.json
data/narrative_memory/migration_manifests/{timeline_id}/{branch_id}.json
```

The existing 0D4-D state path remains the sole branch state authority. New
paths are project-root contained and never silently fall back to flat files or
the active branch.

## Schema and isolation

Events carry immutable identity, complete scope, chapter/source/Canon
references, status, payload, timestamps, fingerprints, and migration
provenance. Snapshots, overrides, retrieval history, and conflicts are scoped
to the same timeline and branch. Archived branches reject mutation; explicit
administrative reads may inspect them without selecting or changing active
state.

## Migration

`NarrativeMemoryMigrationService` supports `dry_run` and `execute`. Dry-run is
zero-write and reports source fingerprints, candidate files, target paths, and
the plan fingerprint. Execute is copy-only, preserves source bytes, adds
`legacy_unscoped` provenance to target records, uses immutable migration
authority plus mutable phase, rejects changed sources/target collisions, and
replays idempotently.

No vector or Chroma code is imported or called. E3 remains outside this phase.

## RC1 closure

Legacy unscoped reads are explicitly marked `legacy_unscoped`, deprecated, and
read-only. Every legacy mutation route now returns
`LEGACY_MEMORY_MUTATION_DISABLED`. E2 treats the D-RC1 branch
`state/{timeline}/{branch}/current.json` as read-only: it neither invents a
second state schema nor writes a competing revision. Migration authority now
binds the dry-run plan fingerprint and supports partial-copy recovery.
