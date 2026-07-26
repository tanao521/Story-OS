# Phase 0D3A2-RC2 — Responsive Layout Correction

## Scope

This correction is limited to the isolated simulator review prototype and its responsive/accessibility specifications. Production templates, production static assets, backend contracts/routes/services, fixtures, Chroma, Obsidian, authority assets, and model/panel execution paths are out of scope.

## Confirmed defects

- At 768×1024, the `@media(max-width:1100px)` two-column `.review-grid` left only about 205px for `.primary-column`. Min-content content from the nested authority/persona/lower grids then painted beneath the fixed 250px audit rail.
- At 390×844, the authority grid used auto-minimum tracks. The long `source_missing` status widened its track and squeezed `RETENTION RISK`, causing `未提供` to break vertically.

## RC2 correction

- Added min-width containment to review, authority, persona, lower-signal, audit, header, and action children.
- Added a `max-width:900px` single-column review flow; audit cards follow the primary flow in a predictable vertical stack, and persona/agreement/conflict cards use one column.
- Added zero-minimum authority tracks at mobile width and stacked the mobile controls.
- Kept short metric values unbroken and rendered the UI-only status label `source_missing` as `来源缺失`; fixture/API enum semantics remain unchanged.

## Acceptance

RC2 is accepted when the two confirmed defects are absent in fresh browser captures, required geometry checks show no unintended sibling overlap, browser console remains empty, and the RC1 regression/protection suite remains green. RC2 closes the 0D3A2 responsive correction gate; it does not authorize implementation of Phase 0D3B.
