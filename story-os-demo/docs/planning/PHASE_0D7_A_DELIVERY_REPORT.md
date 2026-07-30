# Phase 0D7-A Final Delivery — Version-Bound Chapter Assembly Evidence Foundation

## Final Conclusion

**PASSED — READY FOR 0D7-B AUTHORIZATION**

Date: 2026-07-30

## Official Scope

- **Title:** Version-Bound Chapter Assembly Evidence Foundation
- **Objective:** persist and audit one exact-version chapter-assembly evidence
  record without creating a second version, Review, Canon, Commit, memory, or
  vector authority.
- **Excluded:** UI work, Provider/model/network calls, quality scoring,
  automatic prose rewrite, approval, commit/publication, non-main timeline
  work, 0D6 changes, and workspace redesign.

## Version Authority

The evidence scope is:

```text
canonical project ID
-> storage project ID
-> main timeline
-> active branch
-> chapter
-> exact source version label
-> source-content fingerprint
-> active Canon revision (when present)
-> matching Chapter Commit (when present)
-> compilation/candidate provenance (when present)
```

Version files, Canon, Chapter Commit, NarrativeMemory, Narrative Turns and the
0D6-D continuity chain remain source or established authority. The new record
is classified only as `DURABLE_ADVISORY_EVIDENCE`.

## Evidence Contract

- `ChapterAssemblyEvidenceScope` requires project, timeline, branch, chapter
  and source version identity; only `main` is accepted.
- The record identity includes scope, storage identity, exact source
  fingerprint, Canon/Commit linkage, candidate/compilation references and
  active branch-registry revision.
- The durable record is published once under
  `data/chapter_assembly_evidence/main/<branch>/chapter_<n>/<version>/`.
- Identical authority replay returns the same immutable identity.
- A changed version body or branch revision yields `STALE`; absence yields
  `MISSING`; malformed durable data or invalid current authority yields
  `INVALID`. Stale evidence is never returned as `CURRENT`.
- No prose copy is stored. The record retains references, fingerprints and
  structural metadata only.

## Advisory Boundary

The service does not call a Provider and cannot rewrite a source version,
select a version, approve/reject review, commit/publish a chapter, create a
Narrative Turn, mutate Canon/Chapter Commit/NarrativeMemory, touch the 0D6-D
snapshot, or rebuild Vector/Chroma.

## Production Diff

| File | Reason |
| --- | --- |
| `system/chapter_assembly_evidence_service.py` | New bounded evidence service, immutable publication, exact version/source binding, scope and drift validation, and current/stale/missing/invalid status projection. |

No route, frontend, Provider, dependency, schema migration, or sealed 0D6
production file changed.

## Tests

### Focused

```text
tests/test_phase0d7a_chapter_assembly_evidence.py
14 passed, 0 failed, 0 skipped
```

Coverage includes exact source/version binding, canonical project/timeline/
branch/chapter isolation, deterministic replay, content and branch drift,
Canon and Commit linkage, compilation provenance, malformed evidence/provenance,
source/chapter immutability, and absence of review/commit/0D6 continuity
mutation.

### Affected regression

```text
tests/test_phase0d7a_chapter_assembly_evidence.py
tests/test_revision_service.py
tests/test_phase0d6d_a_memory_continuity.py
tests/test_phase0d6d_b_vector_continuity.py

33 passed, 0 failed, 0 skipped
```

### Full regression

```text
collected/executed: 2428
passed: 2428
failed: 0
skipped: 0
warnings: 2 existing PytestUnknownMarkWarning entries for pytest.mark.timeout
exit code: 0
duration: 256.69s
```

## Chromium

**NOT REQUIRED.** 0D7-A adds backend-only advisory evidence. No route,
template, JavaScript, CSS, browser-visible read model, or 0D6-C browser
contract changed.

## Static, Cleanup, and Safety

- Python compile: PASS
- `git diff --check`: PASS (existing CRLF warnings only)
- Phase-specific bytecode directory: 0
- Pytest temporary project root: 0
- Owned browser/fixture/CDP processes: 0
- Real StoryOS project, shared Chroma, registry, Obsidian, Provider/network,
  dependency environment, Git history and Git remote writes: 0

## Sealed Baseline

```text
0D6-A: SEALED
0D6-B: SEALED
0D6-C: SEALED
0D6-D: SEALED
```

The 0D6-D authority chain remains unchanged: NarrativeMemory / Commit / Branch
are source authority; the continuity snapshot is durable continuity authority;
Vector remains `REBUILDABLE_CACHE`.

## RC

```text
RC required: NO
New production defect: NONE
```

## Next

**Await Owner authorization for 0D7-B only.** No UI or review-surface work was
started automatically.
