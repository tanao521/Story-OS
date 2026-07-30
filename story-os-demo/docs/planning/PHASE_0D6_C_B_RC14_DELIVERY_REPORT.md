# Phase 0D6-C-B-RC14 Delivery Report

## Conclusion

`PARTIALLY PASSED — RC15 REQUIRED`

RC14 repaired the confirmed history/action-state production defect. The real
Edge run then exposed a separate backend UUID scope defect at Compile, so the
remaining Chromium matrix was stopped as required.

## Production change

Only `web/static/simulator-context-navigator.js` was changed in RC14.
`history.pushState` now compares the canonical context before and after the
mutation (`project_id || project`, `timeline_id`, `branch_id`, `chapter_id`)
and synthesizes `popstate` only when that context changes. Action/view-only
history entries no longer reset Narrative Turn state.

No backend, ProjectIdentityResolver, vector, Compiler/Review/Commit semantics,
templates, service worker, dependency, or 0D6-B authority changes were made.

## Real Edge evidence

- Edge 150.0.4078.99, independent process, clean temporary profile, localhost CDP, cache disabled: PASS.
- Successor `awaiting_action` Turn reached: PASS.
- Visible recommended action selection survived its URL `pushState`: PASS.
- Feasibility request succeeded with the recommended action payload: PASS.
- Narrative Turn confirmation succeeded: PASS.
- Previous `custom_action_text must be a string` failure: absent.

## RC15 stop evidence

The same real browser flow reached Compile. The browser sent the canonical
ProjectManager UUID in the scope, but the production compiler route returned:

```text
COMPILATION_SCOPE_REQUIRED
Narrative scope is invalid.
```

The current compiler validation compares the canonical request identity with
the active storage directory name (slug). This is an independent backend UUID
boundary defect, outside RC14's allowed history/action-state scope. RC14 did
not modify it; all later completion and Chromium gates were stopped.

## Regression and safety

- RC14 frontend + RC13 frontend contracts: 6 passed / 0 failed / 0 skipped.
- Prior RC13-FV1 ledger retained: 913 passed / 0 failed / 0 skipped.
- Current 0D6 affected suite: 206 passed / 0 failed / 0 skipped (203 prior affected tests plus 3 RC14 contracts).
- New production diff: 1 frontend file only.
- Edge, fixture, profile, project, Chroma/cache residue: 0 after cleanup.
- Provider, StoryOS external network, telemetry, real project writes, new dependencies, and Git writes: 0.

## Next step

Do not authorize FV2 or 0D6-C seal. RC15 must resolve the canonical UUID to
storage identity at the Compiler boundary, then rerun formal completion and the
remaining Chromium acceptance matrix.
