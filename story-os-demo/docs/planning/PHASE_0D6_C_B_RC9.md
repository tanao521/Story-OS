# Phase 0D6-C-B-RC9 — Persistent Embedding Rebind Audit

## Outcome

**BLOCKED — LEGACY EMBEDDING CONTRACT UNRESOLVED.**

RC9 did not modify production code. The mandatory legacy audit found two
incompatible repository contracts sharing the same persistent collection
identity without authoritative collection metadata.

## Conflicting repository contracts

The historical `system/vector_memory.py` path defines
`_COLLECTION_NAME = "storyos_memory"` and `_EMBEDDING_DIM = 384`. Its
collection create/get calls do not pass an embedding function or contract
metadata, so Chroma's default embedding is the effective persisted contract.

The current `VectorClientManager` uses the same collection name and storage
path, but its repository n-gram implementation produces 512-dimensional
vectors. Collections created by this path also carry no authoritative
`embedding_contract`, `embedding_version`, or `embedding_dimension` metadata.

Consequently, a pre-existing metadata-free `storyos_memory` collection can be
a legitimate 384-dimensional legacy collection or a 512-dimensional current
collection. The application cannot distinguish them from repository authority.

## Chroma API audit

The installed Chroma version is 1.5.9. Runtime signature inspection confirmed
that `create_collection`, `get_or_create_collection`, and `get_collection`
accept an explicit `embedding_function`. This is sufficient to repair future
and known-contract reopen paths, but it does not resolve the identity of an
existing metadata-free collection.

## Safety decision

Unconditionally binding the 512-dimensional n-gram implementation would treat
legitimate 384-dimensional collections as 512 and violate the RC9 unsafe
migration gate. Inferring authority from stored vector dimension is explicitly
forbidden. Automatically rewriting, rebuilding, or annotating existing
collections is also forbidden.

RC9 therefore fails closed before production edits, clean-room migration
experiments, or Chromium execution. No FV2 authorization is granted.

> RC10 status update: the owner resolved this ambiguity by reserving
> metadata-free `storyos_memory` as untouched legacy and assigning current
> 512-dimensional writes to `storyos_memory_ngram_v1`. RC10 implemented and
> verified that split; FV2 remains blocked by the formal same-service
> multi-project identity contract.

## Required contract decision

A follow-up phase must define one authoritative compatibility policy before a
safe production fix is possible. It must either:

1. declare metadata-free `storyos_memory` collections to be legacy 384 and
   require an explicit owner-authorized migration/rebuild path; or
2. provide an authoritative persisted discriminator for 384 versus 512
   collections, with unknown/missing metadata failing closed.

The decision must not infer business authority from vector dimension and must
not silently modify existing collections.
