# Simulator Usable Loop Accessibility Contract (0D5-A)

## Landmarks and hierarchy

Use one `header` for the context bar, `nav` for the chapter rail, one `main` for the active workspace, and `aside` for Evidence Rail. Each view has one `h1`; nested panels use ordered `h2`/`h3`. Scope summary remains in the accessibility tree when collapsed.

## Keyboard and focus

All controls are reachable in logical scope → workspace → evidence order. Branch menus, candidate actions, and dialogs support Escape; dialogs trap focus and return it to the triggering control. After confirm/approve/commit, focus moves to the result heading. After a failed read, focus moves to the error heading. No keyboard trap exists outside dialogs.

## Live announcements

Use a polite live region for loading and successful transitions: “Checking feasibility”, “Turn confirmed. Next turn ready”, “Candidate recovered”, and “Chapter committed”. Use assertive announcements only for blocked/stale/error states. Include the remedy, not an apology or vague failure.

## Status and contrast

Every lifecycle/readiness state includes text and, where useful, an icon with a text alternative. Color is never the sole differentiator. Focus indicators remain visible against existing dark surfaces. Warning/error/blocked copy names the changed authority or required action.

## Reduced motion and touch

Respect `prefers-reduced-motion`; use no decorative looping animation. Motion is limited to skeleton-to-ready, stage transition, and recovery acknowledgement. Touch targets are at least 44px; mobile commit confirmation is full-screen and keeps Project/Timeline/Branch/Chapter visible.

## High-risk actions

`Select Branch`, `Archive`, `Restore`, `Approve`, `Commit`, and `Confirm Turn` require clear labels, a single primary action, explicit disabled reason, and post-action focus restoration. Back/Forward and refresh are always read-only.

