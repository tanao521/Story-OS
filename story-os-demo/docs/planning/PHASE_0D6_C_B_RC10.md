# Phase 0D6-C-B-RC10 — Versioned Vector Namespace

## Outcome

**BLOCKED — SAME-SERVICE MULTI-SCOPE CONTRACT GAP.**

The vector namespace, metadata, reopen, clean-room, and formal completion gates
passed. The required same-service Chromium matrix could not be constructed
through formal project and branch authorities because their project identity
contracts disagree.

## Owner Compatibility Decision

- Metadata-free `storyos_memory` is an ambiguous legacy namespace.
- It is not read, modified, renamed, migrated, deleted, or backfilled.
- Current 512-dimensional n-gram writes use
  `storyos_memory_ngram_v1`.
- Automatic legacy migration remains forbidden.

## Versioned N-Gram Namespace

The current manager now owns these fixed constants:

- collection: `storyos_memory_ngram_v1`
- contract: `storyos_repository_ngram`
- version: `1`
- dimension: `512`

Tests-only injected names retain the same metadata contract.

## Embedding Metadata and Reopen Contract

Creation writes the complete Chroma collection metadata once. Every existing
collection open passes the repository n-gram embedding explicitly and then
validates the persisted metadata. Missing contract fields and contract,
version, or dimension mismatches fail closed without rewriting the collection.

Create, same-manager reopen, new-manager reopen, and new-process cold reopen
all use the same 512-dimensional repository implementation. Chroma's default
embedding is not used.

## Legacy Fail-Closed and No-Migration Boundary

The current manager no longer addresses `storyos_memory`. Coexistence tests
proved that a metadata-free legacy collection retains its count and metadata
while the new namespace is created independently. No legacy vectors were read
or copied.

## Clean-Room and Formal Completion

A fresh workspace, Chroma root, random versioned collection, and empty cache
roots were used with a socket guard that rejected non-loopback connections.
Indexing, close, cold reopen, query, production manifest publication,
Compiler, Review, Commit, and `SimulatorLoopStateService` all passed. The
returned and persisted commit IDs matched. No cache/model files or external
connection attempts were observed, and all temporary roots were removed.

## Same-Service Multi-Scope Blocker

`ProjectManager.create_project()` formally registers a UUID `project_id`.
`BranchLifecycleService` and `SimulatorLoopStateService` instead derive
project identity from `ProjectContext.root.name` (the project slug).

A formal temporary Project A demonstrated:

- registry ID: UUID
- branch service ID: project directory slug
- branch create with registry UUID: `Project not found`
- branch create with slug: succeeds, but the slug is not the formal
  ProjectManager/Context Navigator project ID

RC10 forbids handwritten registries, frontend label substitution, dual
servers, and changes to sealed progression/authority semantics. Therefore a
coherent same-service Project A/B plus sibling Branch A/B browser fixture
cannot be built within this phase.

## Chromium, FV2, and Non-Goals

The Chromium delayed GET/POST, history, and exactly-once matrix was not entered
after the formal multi-scope gate failed. No browser PASS is claimed. FV2 is
not authorized. RC10 did not modify frontend, progression, Compiler, Review,
Commit, Provider, dependency, or manifest semantics.
