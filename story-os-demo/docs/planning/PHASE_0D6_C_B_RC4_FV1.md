# Phase 0D6-C-B-RC4-FV1 — Formal Authority & Multi-Scope Browser Matrix

## Outcome

**BLOCKED — TESTABILITY CONTRACT GAP.**

## Executed browser evidence

The existing single-server isolated fixture was run in Chromium with both
`STORYOS_RC4_READINESS_DELAY=3` and `STORYOS_FV_START_DELAY=3`.

- Delayed GET: switching from Simulator to Traditional before release left the
  progression panel and Start control hidden.
- Delayed POST: a real durable start completed, Traditional remained on its
  original URL after release, and no progression panel or Start control was
  rendered.

## Blocking evidence

After the real start created successor chapter 2 and its awaiting-action Turn,
the production `SimulatorLoopStateService` for that exact successor returned
`source_version_id: null` and `VECTOR_MANIFEST_MISSING`. Its candidate section
reported `can_compile: false`. Therefore the required formal
Compiler → Review → Commit completion cannot be executed for the browser's
actual successor scope without adding fixture authority inputs beyond RC4's
current harness.

The same fixture also exposes one project and one branch only. It cannot
execute the required same-server Project A/Project B or sibling Branch A/B
browser switches. No separate-server substitution was used.

## Boundary

No production frontend/backend, sealed service, route, template, schema,
configuration, or dependency change is authorized or made. FV2 remains
unauthorized.
