# Phase 0D7 Implementation Brief — Version-Bound Chapter Quality Evidence and Human Review Closure

**Status:** **SEALED – PHASE 0D7 COMPLETE** (final authority: `PHASE_0D7_SEAL.md`)
**Entry gate:** Phase 0D6-D SEALED  
**Authority source:** `POST_0D6_ROADMAP_AUDIT_REPORT.md` (2026-07-30)

## Objective and user value

Give an author a coherent, exact-version account of chapter assembly quality
before a human review decision: plan adherence, local quality signals,
cross-chapter continuity availability, and evidence freshness. The author keeps
the final decision; the system must not turn subjective scores into Canon or
automatic prose mutation.

## Authority model

| Artifact | Role |
| --- | --- |
| Selected source version, plan, committed predecessor and review decision | SOURCE AUTHORITY |
| 0D6-D continuity snapshot and vector manifest | Existing continuity/cache authority; unchanged |
| 0D7 assembly-evidence record | DERIVED ADVISORY EVIDENCE |
| Quality/continuity scores and recommendations | ADVISORY ONLY |
| Human review approval and commit | Existing commit authority |

An evidence record is valid only when its version identity and content
fingerprint match the review target. It must never write prose, alter source
versions, advance chapters, create a Canon revision, modify memory/vector
authority, or approve/commit a chapter.

## Scope

### Included

- A deterministic version-bound assembly-evidence schema and safe persistence.
- Freshness/source checks for existing quality and continuity inputs.
- Explicit unavailable/stale states rather than inferred success.
- A compact evidence summary in the existing review path after 0D7-A passes.
- Focused regression coverage for draft, edited, manual and committed-source
  read boundaries where applicable.

### Excluded

- Any Provider Live enablement, credential work or external-call validation.
- Automatic quality rewrite, automatic approval, automatic commit, or score as
  Canon authority.
- New model prompts that make a remote Provider mandatory.
- Multi-timeline continuation, vector redesign, memory authority changes or
  reopening 0D6.
- Traditional/Simulator unification, new workspace, navigation redesign or
  broad visual redesign.

## Required slices

### 0D7-A — Assembly Evidence Authority

- **Objective:** derive one fingerprint-bound, advisory record for a selected
  review target from existing plan/quality/continuity evidence.
- **Expected production areas:** a new narrow system service/store and focused
  integration with existing quality/continuity readers; no frontend.
- **Allowed:** deterministic local analysis, safe content fingerprints,
  read-only use of existing reports, isolated test fixtures.
- **Prohibited:** Provider calls, prose/source writes, commit/review authority
  change, real project writes in tests, shared Chroma/Obsidian writes.
- **Exit:** replay is idempotent; wrong source, stale fingerprint, missing or
  corrupt evidence is represented safely; advisory data cannot be consumed as
  commit authority.
- **Browser:** not required.

### 0D7-B — Existing Review-Surface Evidence Closure

- **Objective:** show the exact evidence status in the current review path so a
  human can distinguish fresh, partial and unavailable evidence.
- **Expected production areas:** targeted review route/wire/template/static
  modules already responsible for review display.
- **Allowed:** accessible display and explicit human-action messaging.
- **Prohibited:** new workspace, navigation redesign, auto-approval,
  background refresh, Provider invocation, hidden state inference.
- **Exit:** an exact target's summary is visible; stale/unavailable data cannot
  be displayed as ready; review approval remains explicit.
- **Browser:** required, focused existing-flow acceptance.

### 0D7-FV — Final Verification

- **Objective:** verify source binding, freshness, review isolation, explicit
  human decision and no regression of sealed 0D6 progression/continuity.
- **Production/test changes:** none except verification-owned tests where
  authorized before FV.
- **Browser:** required only if 0D7-B changes the browser-visible review
  contract; otherwise document why it is not required.
- **Exit:** focused and affected regressions pass; all advisory/authority
  boundaries are evidenced.

### 0D7-SEAL — Evidence Reconciliation

- **Objective:** reconcile A/B/FV evidence and request an explicit seal.
- **Allowed:** documentation/status only.
- **Prohibited:** production fixes, scope expansion and automatic next phase.

## Validation and safety

- Start with static compile/import and focused deterministic tests.
- Tests use isolated projects only; no real Provider, network, Obsidian,
  shared Chroma, registry or Git remote writes.
- Preserve 0D6-D classification: NarrativeMemory/Commit/Branch are source
  authority; continuity snapshots are durable transition authority; vector is
  `REBUILDABLE_CACHE`.
- Run a focused browser matrix after B; do not claim Chromium evidence before it
  is executed.
- End each slice with `git diff --check` and scoped residue/process cleanup.

## Stop conditions

- If a desired quality check needs Provider execution to be useful, stop and
  obtain separate Provider authorization rather than silently enabling it.
- If target evidence cannot be tied to a selected version/fingerprint, keep it
  unavailable and do not integrate it as review-ready.
- If the requested UI cannot fit the existing review surface, stop for a
  UX/Frontend Design Specification.
- If a sealed 0D6 authority defect is found, report a sealed-phase reopen
  candidate with evidence; do not repair it in 0D7.

## Model configuration

| Slice | Main model | Reasoning | Agent count | Role | Escalation |
| --- | --- | --- | ---: | --- | --- |
| 0D7-A | Terra | Medium | 1 | Evidence authority implementation | Source/version conflict |
| 0D7-B | Terra | Medium | 1 | Targeted accessible review integration | Browser or accessibility conflict |
| 0D7-FV | Terra | Medium | 1 | Focused verification | Repeatable authority regression |
| 0D7-SEAL | Terra | Medium | 1 | Evidence audit | Material record conflict |

## Final phase state

Phase 0D7 is sealed after 0D7-A, 0D7-B, 0D7-B-RC1, and the successful 0D7-FV
re-run. This brief remains the historical implementation-scope authority; the
final status and reconciliation ledger are in `PHASE_0D7_SEAL.md`.
