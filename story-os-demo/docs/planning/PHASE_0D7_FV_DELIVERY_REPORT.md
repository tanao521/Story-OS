# Phase 0D7-FV Final Verification Report

## Final conclusion

**PARTIALLY PASSED — 0D7-B RC REQUIRED**

0D7-A's advisory evidence states and 0D7-B's individual review-card states
were verified in an isolated project.  Final verification found a browser
stale-response defect in the 0D7-B derived display layer, so Phase 0D7 is not
ready to seal.

## Execution boundary

- Verification-only; production freeze observed.
- One local agent; no Provider, model, external StoryOS network, Obsidian,
  shared Chroma, real project, registry, dependency, Git-history, or remote
  writes were used by the FV checks.
- Browser checks used an isolated temporary project and local fixture server.

## Authority model

```text
Version / Canon / Commit = source authority
0D7-A Assembly Evidence = durable advisory evidence
0D7-B Review Display = derived browser state
Human Review Decision = explicit human authority
```

## Gates observed

| Gate | Result | Evidence |
| --- | --- | --- |
| Exact-version state binding | PASS in isolated state checks | v002 showed only `manual_v002`; no v001 metadata was displayed before the delayed-response scenario. |
| CURRENT | PASS in isolation | v001 returned `CURRENT` with its matching label, identity, fingerprint, and advisory notice. |
| STALE | PASS | v002 had a changed source after evidence publication and visibly returned `STALE`. |
| MISSING | PASS | v003 visibly returned `MISSING`; reading it created no evidence. |
| INVALID | PASS | corrupt v004 evidence visibly returned `INVALID`, without leaking an exception. |
| Advisory / human-review boundary | PASS for observed display path | the card retained the non-decisional notice; no approve, reject, commit, rewrite, or Canon action was invoked. |
| GET read boundary | PASS in observed fixtures and existing tests | route delegates only to `read_status`; no evidence generation was observed. |
| Stale-response isolation | **FAIL** | delayed v001 response overwrote the already-visible v003 `MISSING` card with v001 `CURRENT`. |
| Rapid switching | NOT RUN | halted after the mandatory stale-response gate failed. |

## Reproduction of blocking defect

1. Start an isolated fixture where `manual_v001` has current evidence and its
   evidence GET is deliberately held.
2. View `manual_v001`; the evidence card enters loading.
3. Switch to `manual_v003`, which correctly displays `MISSING`.
4. Release the held v001 GET.
5. The card changes to `CURRENT` for `manual_v001` while the user is still
   viewing v003.

Root cause observed during audit: `loadReviewAssemblyEvidence()` has no
request/version epoch or equivalent current-view guard before it renders its
asynchronous response.  This is a 0D7-B display/read-model defect.  No
production repair was made in FV.

## Current combined focused matrix

```text
Collected/executed: 75
Passed: 75
Failed: 0
Skipped: 0
Exit code: 0
Duration: 57.75s
```

The matrix included 0D7-A/B evidence, VersionManager, RevisionService, review
gate/quality/archive, ChapterCommitter, and 0D6-D memory/vector continuity
tests.

## Static

```text
python -m py_compile system/chapter_assembly_evidence_service.py web/routes.py: PASS
node --check web/static/app.js: PASS
```

## Full regression

Not run.  FV's mandatory browser stale-response gate failed first; the
authoritative FV contract requires classification and stop rather than an
opportunistic production repair or a misleading final pass.

## Cleanup and safety

- FV browser tabs finalized.
- Owned fixture server stopped.
- Owned fixture workspaces, logs, and bytecode cache removed.
- No real StoryOS project or production source file changed.
- The only FV artifact is the isolated browser fixture source at
  `tests/_phase0d7fv_browser_fixture_server.py`.

## Sealed baseline

```text
0D6-A: SEALED
0D6-B: SEALED
0D6-C: SEALED
0D6-D: SEALED
0D7-A: PASSED
0D7-B: RC REQUIRED
```

## Next

Authorize a narrow **0D7-B RC** to add a current-view/request guard to the
asynchronous review-evidence renderer, then rerun the full 0D7-FV matrix.
