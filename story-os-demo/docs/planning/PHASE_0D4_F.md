# Phase 0D4-F — Confirmed Turn Compilation

Status: PASSED (implementation scope)

`NarrativeChapterCompiler` selects confirmed, applied Turns from the explicit
project/timeline/branch/chapter scope, orders them by transition sequence, and
creates a deterministic manual Candidate through `VersionWriterFacade`.
Compilation records immutable operation authority under
`data/narrative_compile/operations/` and advances only append-only Turn
transitions. It never writes Canon, Chroma, or NarrativeMemory.

`NarrativeChapterCommitService` requires a human-approved Candidate and a fresh
branch/source scope, then calls the existing `ChapterCommitService.commit_chapter`
with the complete `VectorScope`. Committed transitions are appended after a
successful durable commit result. Compile and commit have separate authorities
and replay-safe phase records.

HTTP endpoints are available at `/api/narrative-chapter/compile`, `/commit`,
and `/candidates/{candidate_id}`. Requests require the complete scope and all
responses use `Cache-Control: no-store` with safe error envelopes.
