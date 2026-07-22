# Phase 0D3A2 design input brief

## Product and user task

Story OS is a professional local novel-writing and reader-simulation workbench. Simulator mode is a sibling of traditional writing mode inside one product. The first task is to inspect a chapter's deterministic Reader Persona Panel Review without editing the story or triggering execution.

## Design inputs

- **Page map:** mode/context entry → chapter review workbench → explicit Panel Run deep link → state containers.
- **Priority:** review status and source context; authoritative panel and persona order; model supplement; conflicts and agreements; evidence/execution/staleness/usage; structured warnings.
- **Components:** SimulatorModeShell, ReviewHeader, ReviewStatusBanner, SelectionSummary, AuthoritativePanelSummary, PersonaReviewCard, AgreementGroupList, ConflictGroupList, EvidenceSummary, ExecutionSummary, UsageSummary, StalenessSummary, StructuredWarningList, LoadingSkeleton, ApiErrorBoundary, Empty/Failed/SourceMissing states.
- **Visual constraints:** dense but legible professional console; reuse Story OS language; no marketing hero, giant undifferentiated card, or decorative gradient system. Authority and model feedback must be visually distinct. Agreement/conflict need labels/icons in addition to color. stale/partial/failed must not resemble ready.
- **Technical constraints:** existing FastAPI + Jinja2 + vanilla JS/CSS; no forced React/Vue migration or new bundler. Read-only GET APIs only.
- **Responsive/accessibility:** desktop two-column review with single-column collapse; keyboard-visible focus; semantic headings/regions; screen-reader status text; reduced-motion support; no color-only meaning.
- **Fixture set:** all matrix variants in `simulator_review_state_matrix.md`, including safe 404 envelope.

## Skill hand-off and acceptance

`frontend-design` is available and was read. In 0D3A2 it may turn this brief into an intentional visual direction, wireframe, and implementation plan, using actual Story OS assets and the fixture set. Before invoking it, prepare a representative redacted JSON fixture, exact viewport targets, existing CSS token inventory, and product approval of the recommended mode-switch URL shape. Acceptance: authority/model separation is obvious, every matrix state is testable, deep links retain context, no chapter text or sensitive internals leak, and the result remains recognizably Story OS.
