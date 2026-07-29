# Phase 0D6-C-B-RC5 — Formal Successor Fixture & Same-Service Matrix Closure

## Purpose

Resolve the RC4-FV1 fixture gaps without production changes, fake authority,
or live vector/provider access.

## Fixture root cause

The browser successor is correctly created by `ChapterLifecycleService`, but
its lifecycle version initializer delegates to `initialize_chapter_versions`.
That production function writes an empty version index when no work version
exists; it does not create or select a source. Consequently the successor
read-model exposes `source_version_id: null`.

The read model finds branch vector readiness only at
`data/chroma/manifests/<timeline>/<branch>.json`. The official publisher is
`sync_branch_index`, which writes the VectorClient collection before publishing
the integrity-protected manifest. Hand-writing the manifest or its fingerprint
is explicitly forbidden, while invoking that publisher would perform a Chroma
write, also explicitly forbidden by RC5.

## Result

RC5 is blocked before fixture modification: a formally valid vector manifest
requires an unauthorized Chroma write, and an unblocked source needs a new
work-version fixture input. The latter alone cannot satisfy the former.

## Production freeze boundary

No production frontend/backend, sealed service, route, template, schema,
configuration, or dependency is changed.

## FV2 gate

FV2 remains unauthorized. No multi-project or sibling-branch browser matrix is
claimed because the formal successor prerequisite cannot be legally prepared.
