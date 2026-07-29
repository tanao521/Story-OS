# Simulator Usable Loop Interaction and State Contract (0D5-A)

## State machine

| State | Entry condition | Visible regions | Primary action | Secondary actions | Allowed mutations | URL / recovery / announcement |
|---|---|---|---|---|---|---|
| ENTRY | simulator opened | context + rail | Resolve scope | change project | none | `mode=simulator`; announce scope loading |
| SCOPE_REQUIRED | required IDs missing | scope prompt | Choose scope | return to shell | none | scope params only; announce missing fields |
| BRANCH_SETUP | scope valid, no active branch | branch panel | Select active branch | create branch | explicit select/create | branch params; announce setup required |
| TURN_LOADING | turn requested | workspace skeleton + evidence | none | cancel view load | none | `view=turn&turn_id`; loading live region |
| TURN_READY | context/plan valid | turn workspace | Choose action | open evidence/history | none | selected action in memory only |
| FEASIBILITY_CHECKING | action submitted | feasibility panel | none | cancel | none | announce check started |
| FEASIBILITY_READY | check complete | feasibility + action | Preview consequence | change action | none | announce allowed/cost/block status |
| PREVIEW_LOADING | preview requested | preview skeleton | none | return to feasibility | none | announce preview loading |
| PREVIEW_READY | preview complete | preview + evidence | Confirm turn | edit action | none until confirm | no approval in URL |
| CONFIRMING | explicit confirm | locked workspace | none | no duplicate submit | confirm mutation only | operation remains durable, announce submitting |
| CONFIRM_RECOVERING | timeout/unknown response | recovery panel | Recover result | back to history | recovery read only | durable result lookup; announce recovery |
| TURN_RESULT | durable confirm result | result acknowledgement | Continue to next turn | open history/evidence | none | result ID in state; announce completion |
| NEXT_TURN_LOADING | continue chosen | skeleton | none | history | none | new `turn_id`; announce next turn |
| CANDIDATE_COMPILING | compile requested | candidate skeleton | none | cancel view | compile mutation only | candidate ID when durable |
| CANDIDATE_PENDING_REVIEW | candidate pending | candidate review | Review candidate | history/evidence | none | `view=candidate&candidate_id`; announce pending |
| CANDIDATE_APPROVED | durable approval | candidate + approval evidence | Commit chapter | return to review | approval authority only | approval is durable, never URL-only |
| CANDIDATE_REJECTED | durable rejection | candidate outcome | Return / recompile | history | rejection mutation | announce candidate returned |
| CANDIDATE_STALE | freshness mismatch | stale banner + evidence | Refresh / recompile | history | none | fail closed; announce changed authority |
| COMMIT_CONFIRMATION | approved candidate | confirmation dialog | Commit chapter | Back to review | none until confirm | focus trap; announce impact |
| COMMITTING | explicit commit | locked dialog + evidence | none | none | commit mutation only | durable operation ID internal |
| COMMIT_RECOVERING | unknown commit response | recovery panel | Recover commit result | history | read-only recovery | never call commit twice |
| CHAPTER_COMPLETE | durable commit result | completion panel + history | Start next chapter | inspect evidence | explicit next chapter only | announce Canon revision and branch |
| BLOCKED | lifecycle/freshness/readiness blocks action | reason + remedy | Resolve block | inspect evidence | none | announce exact remedy |
| ERROR | unrecoverable read/error | error boundary | Retry read | return to safe scope | none | preserve scope, announce error |

Rules: only the primary action may mutate in a state; Back/Forward and refresh never mutate; pending, stale, archived, or inactive states fail closed.

## Entry and scope resolution

On `mode=simulator`, resolve project → timeline → chapter → source → branch. If an unfinished durable Turn/Candidate/commit recovery exists, show its recovery state before creating a new plan. If branch is absent, show Branch Setup rather than silently selecting the first branch. Browse and Select are different controls and labels.

## Multi-Turn transition

`Confirm turn` is the only mutation. On success: append the current Turn to History, show a short result/state-delta acknowledgement, clear action and preview, update `turn_id`, load the next plan, and announce “Turn confirmed. Next turn ready.” A lost response enters recovery and reads the durable result using the same operation authority; it never creates a new operation.

## Branch controls

Create produces an inactive branch and does not auto-select it. Select requires explicit confirmation and shows the target lifecycle/readiness. Archive requires a replacement when archiving the active branch. Restore returns an open branch but does not auto-select it; not-ready/rebuilding readiness remains visible and blocks normal business actions.

## Turn History

History items show sequence, action, result summary, state delta, logical time, lifecycle, included candidate, and committed chapter. `cancelled`, `superseded`, and `recovery-restored` are explicit labels. History is immutable and evidence expands inline; internal operation files are never shown.

## Candidate review, approval, and commit

Candidate review separates base chapter, compiled Turn content, structured/non-compilable Turns, warnings, and evidence. Pending → `Review candidate`; approved → `Commit chapter`; rejected → `Return / recompile`; stale → `Refresh / recompile`; committed → read-only completion. Approval is a durable authority containing approver, time, scope, and candidate fingerprint. If no backend approval API exists, mark `REQUIRED_BACKEND_GAP_FOR_0D5-B`; never fake approval locally.

Commit confirmation names Project, Timeline, Branch, Chapter, Candidate, Canon revision, expected result, existing ChapterCommitService, possible post-jobs, and no cross-branch merge. Recovery displays the durable result and Canon revision and never calls commit again.

