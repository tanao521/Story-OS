# Phase 0D6-C-B-RC7 Delivery Report

## Outcome

**FAILED — EXTERNAL NETWORK SAFETY GATE.**

## Production diff audit

- Modified production files: `system/vector_client_manager.py`,
  `system/vector_index_lifecycle.py`.
- New constructor parameters: explicit `client_factory` and
  `collection_name`; defaults retain the prior production path.
- New authority-call parameter: optional `vector_client_manager`; omission
  retains the prior `VectorClientManager()` call.
- HTTP/environment/config exposure: 0.
- Global mutable setter: 0.
- Manifest, compiler, progression, and sealed authority semantic changes: 0.

## Successful authority evidence

The isolated run produced vector-ready state, selected `manual_v001`, one
Candidate, an approved Review, a Commit, `completed=true`, and identical
returned/durable commit IDs. Instance-isolation and default-path tests passed.

## Safety failure

Chroma automatically downloaded its default ONNX model from a public endpoint
during the first real run. This violates RC7's zero-public-network contract,
even though the StoryOS services themselves made no external call. The
temporary project also initially encountered a Windows Chroma handle during
cleanup; after process termination the exact validated temporary directory was
deleted successfully.

The manager now supplies the repository's local n-gram embedding function to
an injected Chroma collection when Chroma is available, preventing the default
embedding selection. A cold-cache blocked-network rerun was not available in
this phase, so the safety gate cannot be retroactively passed.

## Matrix and recommendation

The Chromium Project A/B, sibling Branch A/B, delayed GET/POST, history, and
exactly-once matrix was not run after the safety failure. FV2 is not
authorized. A narrowly scoped follow-up must verify the corrected injected
collection under an enforced non-local network block and then execute the full
matrix.
