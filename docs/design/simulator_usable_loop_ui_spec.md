# Simulator Usable Loop UI Specification (0D5-A)

Status: DESIGN_ONLY. No production UI/API changes are authorized in 0D5-A.

## Design thesis

The simulator is a quiet night-editing workbench for making one accountable story decision at a time. The screen should feel like an annotated manuscript desk: dense evidence, calm hierarchy, and one unmistakable next action. It is not a chat surface, dashboard, or marketing hero.

## Direction

* **Palette:** existing `--bg-workspace` / `--bg-elevated` surfaces, `--text-primary`, `--text-muted`, `--story-gold` for authority, `--status-success`, `--status-warning`, `--status-error`, and `--accent-primary` only for informational focus. Never use color alone for state.
* **Typography:** retain existing `--font-editorial` for chapter prose/headings, `--font-body` for controls and explanatory copy, and `--font-mono` for IDs, revisions, timestamps, and evidence labels.
* **Layout:** desktop four-zone workbench: Global Context Bar → Chapter Progress Rail → Main Workspace → Evidence/Status Rail. Hairline rules and compact rows encode scope; cards are shallow and rectangular, not floating app tiles.
* **Density:** `DESIGN_VARIANCE=5`, `MOTION_INTENSITY=2`, `VISUAL_DENSITY=7`. Motion is reserved for loading, state transition, and recovery acknowledgement.
* **Signature:** the **authority spine** is a continuous 2px rule beneath the context bar. Its segments carry scope, active branch, Canon revision, and current stage. A break or amber segment means “re-check authority,” never merely “warning color.”

## Information architecture

```text
SimulatorLoopShell
├─ SimulatorContextBar
│  ├─ Project / Timeline / Chapter / Source Version
│  ├─ Active Branch (Browse vs Select)
│  └─ Canon Revision / Vector Readiness
├─ ChapterProgressRail
│  └─ Turns → Candidate → Review → Commit → Complete
├─ MainWorkspace (one active view)
│  ├─ TurnWorkspace
│  ├─ TurnHistory
│  ├─ CandidateReview
│  ├─ CommitConfirmation
│  └─ ChapterCompletion
└─ EvidenceRail
   ├─ Scope evidence
   ├─ State delta / consequence
   ├─ Readiness and stale warnings
   └─ Recovery / commit result
```

The rail and context remain visible while the main workspace changes. Secondary information is collapsible; the primary action never competes with another mutation.

## Desktop wireframe

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ authority spine: Project · Timeline · Chapter · Branch · Canon · readiness  │
├───────────────┬───────────────────────────────────────────────┬─────────────┤
│ chapter rail  │ active workspace                              │ evidence    │
│               │ Turn / History / Candidate / Commit / Complete│ + status    │
│ Turns         │                                               │             │
│ Candidate     │ one primary action                             │ scope       │
│ Review        │                                               │ delta       │
│ Commit        │                                               │ recovery    │
│ Complete      │                                               │             │
└───────────────┴───────────────────────────────────────────────┴─────────────┘
```

## Responsive behavior

Desktop uses all four zones. Tablet collapses Evidence Rail into a drawer and Branch Controls into a side drawer while Candidate content stays central. Mobile is a single column: context summary is collapsible but scope fields remain visible; History and Candidate are separate views; commit confirmation is full-screen; touch targets are at least 44px.

## Copy and action vocabulary

Use plain, stable verbs: `Select branch`, `Create branch`, `Archive branch`, `Restore branch`, `Confirm turn`, `Review candidate`, `Approve candidate`, `Commit chapter`, `Start next chapter`. Never expose operation filenames or internal authority jargon as user-facing labels. Recovery copy states what durable result was found and what action is safe next.

## Non-goals

No new visual system, gradients, marketing hero, chat metaphor, video-editor timeline, equal-weight button grid, production code, API, schema, mutation, or provider call.

