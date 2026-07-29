# Phase 0D6-C-B-RC8 Delivery Report

## Final status

**PARTIALLY PASSED — RC9 REQUIRED**

## Phase gates

| Gate | Result |
| --- | --- |
| Fresh workspace and fresh cache roots | PASS |
| Non-loopback network guard | PASS; 0 attempts observed |
| Local n-gram indexing and formal completion chain | PASS |
| Persisted injected-collection query revalidation | FAIL; 512-to-384 dimension mismatch |
| Chromium multi-scope/delay/history matrix | NOT RUN; vector precondition failed |

## Root cause

`VectorClientManager.get_collection()` supplies the repository n-gram
embedding when creating an injected collection, but a later retrieval of that
persisted collection exposes Chroma's `DefaultEmbeddingFunction`. A query then
uses a 384-dimensional default embedding against the 512-dimensional n-gram
collection and raises `InvalidArgumentError`.

## Required RC9 work

Repair the production collection re-open path so every injected and default
client binds the repository n-gram embedding before query/add operations;
repeat the cold-cache blocked-network probe, then run the complete Chromium
multi-scope and delayed-response matrix. RC8 made no production change.
