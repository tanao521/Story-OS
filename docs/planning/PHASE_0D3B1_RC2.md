# Phase 0D3B1-RC2 — Human-Assisted Production Browser Acceptance

## Scope

Close the remaining production-browser acceptance work through a user-operated local browser. No browser dependency installation, backend modification, model/provider execution, story write, or next-phase work is allowed.

## Corrections during acceptance

Two QA integration issues were found and corrected:

1. The isolated harness was hidden after production initialization. Harness startup now runs after `DOMContentLoaded` and restores only its isolated mount.
2. The legacy workspace was visible through `/api/status` but `/api/projects/active` remained null. The frontend now accepts the server-listed project only when exactly one project is both `valid` and `legacy`; it reuses the server-provided safe id and never places `project_root` in the URL.

## Acceptance disposition

The user confirmed that manual acceptance was completed and supplied a visible QA ready-state screenshot. Automatic HTTP checks, regression tests, isolation scans, and protection checks pass. However, the seven required screenshot files are not present in the repository or located under their required names, and no Console/Network export was supplied. The phase therefore remains `PARTIALLY PASSED` rather than inferring a file-backed visual seal from verbal confirmation.

## Gate remaining

Save the seven named PNG files under `docs/design/qa/simulator-panel-review-production/screenshots/`. Once present, verify their dimensions/content and attach any Console/Network transcript needed for audit. Do not enter another phase until that evidence is closed.
