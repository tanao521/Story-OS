# Phase 0D6-C-B-RC6 — Ephemeral Vector Authority

## Purpose

Use RC6's explicit authorization for a temporary local Chroma collection to
prove the official source and vector authority path without production edits.

## Gate 0 result

The test-local `ProjectContext` stores Chroma only below its temporary
`data/chroma` path. `VersionWriterFacade` successfully creates and selects the
successor source. However, the actual `sync_branch_index` invocation cannot
obtain a local collection in this environment. It returns without publishing a
manifest and its formal verification raises `BranchVectorNotReady`.

## Boundary

No Provider, external Chroma, real project, shared collection, Obsidian,
production code, or Git write is in scope. The temporary VectorClient is
closed before the test returns.

## Matrix gate

This is `BLOCKED — TEST-LOCAL VECTOR AUTHORITY UNAVAILABLE`. Production does
not expose a test-local VectorClient injection seam, and RC6 forbids modifying
it. FV2 remains unauthorized.
