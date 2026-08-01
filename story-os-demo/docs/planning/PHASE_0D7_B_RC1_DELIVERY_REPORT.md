# Phase 0D7-B-RC1 Delivery Report

## Conclusion

**PASSED — READY TO RE-RUN 0D7-FV.**

RC1 repairs the review-evidence stale-response race without changing the
review-evidence contract, persistence, or review workflow semantics.

## Root cause and repair

When an evidence request for an older selected version completed after the user
had selected a newer version, its response could still render into the active
review card.  The prior implementation did not associate the asynchronous
response with the version-selection context that initiated it.

`web/static/app.js` now creates a review-evidence request token when
`loadVersionContent` begins.  The token records an epoch, project generation,
source type, and version.  `reviewEvidenceRequestOwnsCurrentView` verifies that
the request is still the latest request and still matches the active project and
selected version before either a successful response or an error can render.

The production change is limited to `web/static/app.js`.

## Verification

- Static syntax check: `node --check web/static/app.js` — passed.
- Focused affected regression set — **75 passed** in 57.56 seconds.
- Full regression suite — **2431 passed** in 256.78 seconds.
  - Two existing `PytestUnknownMarkWarning` warnings remain for
    `pytest.mark.timeout` in `tests/test_phase0c2_rc2_vr.py`; they are not
    caused by this repair.
- Browser delayed-response scenario — passed:
  1. Open delayed `manual_v001` evidence request.
  2. Switch to `manual_v003`, whose evidence is missing.
  3. Release the older `manual_v001` response.
  4. The visible card remains **MISSING** for `manual_v003`; no v001 metadata
     reappears.
- Browser rapid-switch scenario — passed:
  `v001 -> v002 -> v003 -> v002` ends with the v002 **STALE** card and v002
  metadata only.
- Browser state matrix — passed: **CURRENT**, **STALE**, **MISSING**, and
  **INVALID** all retain their established render behavior.

The browser verification uses the focused local fixture server at
`tests/_phase0d7fv_browser_fixture_server.py`; it introduces no production
runtime behavior.

## Safety and scope

- No review mutation was invoked: approve, reject, commit, rewrite, and Canon
  actions were all zero.
- No provider call, project-writing API call, evidence regeneration, or
  persistence change was made.
- No Phase 0D6 seal was modified or reopened.
- No commit, push, pull request, or other remote write was performed.

## Next step

Await owner authorization to re-run **Phase 0D7-FV** against this repaired
frontend.
