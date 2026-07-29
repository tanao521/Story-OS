# Phase 0D6-C-B-RC8 — Clean-Room Offline Vector Revalidation

## Outcome

**PARTIALLY PASSED — RC9 REQUIRED.**

RC8 did not change production wiring. The clean-room authority and formal
Compiler → Review → Commit chain passed under a fresh temporary workspace and
fresh third-party cache roots, with all non-loopback socket connections
actively rejected. No blocked-network attempt was observed during indexing or
commit, and the temporary cache contained no model files.

## Evidence

- An injected `VectorClientManager` created a fresh local `PersistentClient`.
- `sync_branch_index(..., operation_type="rebuild")` returned `success`,
  `vector_ready=true`, and one indexed record.
- The formal compiler, approval review, and commit returned a durable commit;
  the progression read model reported `completed=true`.
- `HF_HOME`, `TRANSFORMERS_CACHE`, `SENTENCE_TRANSFORMERS_HOME`, and
  `XDG_CACHE_HOME` were redirected to a new temp directory. The directory was
  empty of model files and was removed after all Chroma handles were closed.
- The socket guard allowed only `127.0.0.1`, `localhost`, and `::1`; its
  non-local attempt list remained empty.

## Blocking finding

The same clean-room process then queried the persisted injected collection.
Chroma reconstructed `DefaultEmbeddingFunction` (384 dimensions) instead of
the repository n-gram function (512 dimensions), and failed with:

`Collection expecting embedding with dimension of 512, got 384`.

This is a production VectorClient re-open/wiring defect. RC8 explicitly
forbids production edits; correcting it requires RC9. Therefore RC8 does not
claim vector revalidation closure and does not authorize FV2.

## Chromium boundary

The full same-service Project A/B, sibling Branch A/B, delayed GET/POST,
history, and exactly-once Chromium matrix was not run because the required
clean-room vector precondition failed. No Chromium PASS is claimed.

## Safety and scope notes

Only new temp roots were created and removed. Existing user Chroma/model cache
was not read, deleted, or used as RC8 input. No provider, remote Chroma, real
project, Obsidian, Git, dependency installation, or production frontend change
was performed.
