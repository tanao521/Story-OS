# Phase 0D5-P — Simulator Usable Loop Productization Preflight

Status: **PASSED**  
Implementation: **NOT ENTERED**  
Production live / canary: **OFF / NOT AUTHORIZED**

0D5-A is now authorized for design-only work. Its design closure is documented separately; 0D5-B remains not authorized.

## Scope and safety

This was a read-only productization preflight. No production source, test, database, provider, network, Git, Canon, Chroma, or real-project data was changed. Only the four planning/evidence documents listed in the delivery report were added.

## Phase conflict check

No `PHASE_0D5*` or `PHASE_0E*` planning files were present before this preflight. The requested numbering is retained; 0D5-A is not entered.

## Current usable journey

The simulator shell exposes project/timeline/chapter/source/panel-run context and a read-only mock-run/review surface. The narrative-turn workspace exposes context, recommended actions, feasibility, consequence preview, and confirm. Entry is not a complete product journey: the visible mode switch lands on `reader-panel-review`; narrative-turn requires a URL view plus `branch_id`, and the first branch selection does not rebind the plan.

After confirm, the backend has durable transition/recovery machinery, but the browser does not advance to a new Turn, render a Turn History entry, or offer compile → candidate review → approve → commit → next chapter controls. Branch CRUD and Chapter Candidate F APIs are present but largely API/internal-only.

## Capability classification

| Capability | Evidence | Classification |
|---|---|---|
| Context navigator | `/api/simulator/context`, visible simulator controls | IMPLEMENTED_AND_VISIBLE |
| Turn context/plan | `/api/narrative-turn/context`, `/plan`, scoped workspace | PARTIALLY_CONNECTED |
| Feasibility/preview | API plus visible panels | IMPLEMENTED_AND_VISIBLE |
| Confirm Turn | POST `/api/narrative-turn/confirm`, visible gated button | PARTIALLY_CONNECTED |
| Next Turn | confirm rebind only; no next-turn route or UI | PARTIALLY_CONNECTED |
| Turn History | journal/internal stores; no route or UI | IMPLEMENTED_INTERNAL_ONLY |
| Branch list/select | APIs and dynamic branch selector | PARTIALLY_CONNECTED |
| Branch create/archive/restore | lifecycle APIs, no production controls | IMPLEMENTED_API_ONLY |
| Compile Candidate | `/api/narrative-chapter/compile`, no UI action | IMPLEMENTED_API_ONLY |
| Candidate detail | GET candidate endpoint, no UI | IMPLEMENTED_API_ONLY |
| Candidate review/approval | no F review/approval route or UI | MISSING |
| Commit | `/api/narrative-chapter/commit`, no UI | IMPLEMENTED_API_ONLY |
| Chapter progression | traditional route only; no simulator continuation | PARTIALLY_CONNECTED |
| Session recovery | URL/in-memory context only | PARTIALLY_CONNECTED |

Category labels overlap and are not additive.

## Traditional Writing Mode Protection Matrix

| Existing workflow | Shared surface | 0D5 risk | Required regression |
|---|---|---|---|
| Chapter generation | `/api/run-chapter`, `commands.run_chapter_command` | simulator context/version bleed | run-chapter and ChapterCommitService tests |
| Quality/review | `/api/review/*`, quality checker | F candidate review confusion | quality/review route and UI tests |
| Version selection | VersionManager, `/api/versions/select` | simulator changing selected version | VersionManager/version-route tests |
| Manual editing | `/api/manual/save`, manual editor | simulator writes leaking into editor | manual editor tests |
| Revision/Canon | RevisionService, `/api/revisions/*` | simulator bypassing Canon path | revision and commit-service tests |
| Navigation | project manager and app shell | mode/context URL bleed | frontend context tests |

## Preflight decision

The backend foundations are sufficient to plan productization, but the required three-Turn browser loop and candidate review/approval evidence are absent. This is therefore **PARTIALLY PASSED — FACT VERIFICATION REQUIRED**. Stop here; do not enter 0D5-A until the product owner accepts the gap map and evidence plan.
