# Simulator Usable Loop Component Contract (0D5-A)

All components are design contracts only. Inputs are read models or existing DTOs; mutations must be emitted as named intents to the existing service/API layer. Components must expose loading, empty, error, and blocked states and a semantic landmark.

| Component | Responsibility / inputs | Emitted actions | Landmark / forbidden behavior |
|---|---|---|---|
| `SimulatorLoopShell` | owns view routing, scope, one active workspace | `changeView`, `reloadScope` | `main`; no mutation on route change |
| `SimulatorContextBar` | renders project/timeline/chapter/source/branch/Canon/readiness | `changeScope`, `openBranchControls` | `banner`; never imply Browse is Active |
| `ChapterProgressRail` | renders Turns → Candidate → Review → Commit → Complete | `openStage` | `navigation`; not marketing steps |
| `BranchControlPanel` | lists active/open/archived and readiness | `create`, `select`, `archive`, `restore` | `region`; never auto-select after create/restore |
| `BranchStatusChip` | lifecycle + readiness text/icon | none | status text required; no color-only state |
| `VectorReadinessIndicator` | ready/rebuilding/not-ready | `openEvidence` | status text and tooltip; no false “ready” |
| `NarrativeTurnWorkspace` | situation, action, feasibility, preview | `chooseAction`, `confirmTurn` | `region`; one confirm control |
| `TurnResultAcknowledgement` | result and state delta | `continueNextTurn`, `openHistory` | `status`; result must be durable |
| `TurnHistoryPanel` / `TurnHistoryItem` | immutable narrative sequence and evidence | `openTurn`, `openEvidence` | `region`; no edit/delete |
| `CandidateList` | candidates scoped to chapter/branch | `openCandidate` | `region`; no local approval state |
| `CandidateReviewWorkspace` | content, warnings, origin/evidence, freshness | `approve`, `reject`, `recompile` | `region`; pending cannot commit |
| `CandidateScopeHeader` | candidate scope/fingerprint/review status | `openEvidence` | `banner`; shortened fingerprint only |
| `CandidateContentView` | base/new/structured content separation | `toggleAnnotations` | `article`; not a code diff editor |
| `CandidateEvidenceRail` | scope, included Turns, freshness, authority | `openEvidence` | `complementary`; read-only |
| `ApprovalControl` | durable approve/reject intent | `approve`, `reject` | `region`; never fake approval in client state |
| `CommitConfirmationDialog` | explicit impact summary | `commit`, `backToReview` | `dialog`; focus trap, one primary |
| `CommitRecoveryPanel` | durable result and Canon revision | `recover`, `openCompletion` | `status`; no retry mutation |
| `ChapterCompletionPanel` | committed chapter, revision, included Turns, readiness | `startNextChapter`, `openHistory` | `region`; next chapter is explicit |
| `SimulatorErrorBoundary` | actionable read/recovery errors | `retryRead`, `returnToScope` | `alert`; preserve scope, no silent fallback |

## Shared component rules

Every action has a stable verb from the UI vocabulary. Disabled controls explain why. Async controls expose `aria-busy`, preserve focus, and prevent duplicate submits. Internal operation IDs, raw artifact paths, and provider details are not rendered.

