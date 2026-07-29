# Phase 0D6-C-B-RC7 — Minimal VectorClient Injection Seam

## Purpose

Add an explicit Python-only, instance-scoped VectorClient construction seam
while preserving the default production singleton and authority semantics.

## Injection contract

`VectorClientManager(client_factory=..., collection_name=...)` creates a
non-singleton manager. Calling `VectorClientManager()` with no arguments
continues to return the existing production singleton. `sync_branch_index`
accepts an optional manager; omission follows the original path.

The seam has no HTTP, environment-variable, configuration, user-data, global
setter, or dynamic-import trigger.

## Verification boundary

The injection and formal source/vector/compiler/review/commit chain were
exercised, but Chroma attempted and completed an automatic public model
download during the first real local run. The matrix therefore stopped at the
network safety gate. No Chromium scope-isolation PASS is claimed.

## FV2 gate

FV2 remains unauthorized. A follow-up must prove a cold-cache local Chroma run
with all non-local traffic blocked, then execute the full same-service matrix.
