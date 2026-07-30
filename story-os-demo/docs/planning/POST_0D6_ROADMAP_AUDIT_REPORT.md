# Post-0D6 Roadmap Authority Audit Report

**Status:** PASSED — NEXT PHASE DEFINED  
**Date:** 2026-07-30  
**Mode:** read-only / planning-only. No production, runtime, test, Provider,
Chroma, registry, Obsidian, dependency, or Git mutation was performed.

## 1. Final decision

```text
NEXT AUTHORITATIVE PHASE = Phase 0D7 — Version-Bound Chapter Quality Evidence and Human Review Closure
```

This is a new, deliberately narrow product-quality phase. It is not a reopening
of 0D6 and it is not authorization to implement 0D7. Its purpose is to make the
existing human review gate receive trustworthy, version-bound, chapter-level
quality and continuity evidence before a chapter is committed.

## 2. Current sealed baseline

```text
0D6-A: SEALED
0D6-B: SEALED
0D6-C: SEALED
0D6-D: SEALED
```

The current final authority is `PHASE_0D6_D_SEAL.md`: the main-timeline chain
now has immutable Branch/Memory continuity snapshots, rebuildable scoped vector
cache, and manifest recovery. Its evidence ledger records A+B 99/0/0, affected
146/0/0, and full 2414/0/0 with two pre-existing warnings. No browser contract
changed in D, so Chromium was correctly not required.

## 3. Authority recovery and precedence

| Roadmap statement | Classification | Reason |
| --- | --- | --- |
| 0D6-D Seal | CURRENT AUTHORITY | Latest owner-authorized final record; it closes the 0D6 main-continuity seam and requires fresh authorization for later work. |
| 0D6-D FV and implementation brief | HISTORICAL CONTEXT | Their implementation/FV statuses are superseded as final status anchors by the D seal, but their scope and verification history remain valid evidence. |
| 0D7-P recommendation of 0D6-D | SUPERSEDED | It was correct when D was unexecuted. D is now sealed, so it cannot remain the next phase. |
| `PROJECT_ROADMAP.md` v2.4/v2.5 entries | HISTORICAL CONTEXT | They describe an earlier product layer and do not supersede sealed 0D6 authority or define a current next implementation phase. |
| Existing 0D7 definition | UNEXECUTED BUT VALID | No historical frozen 0D7 specification exists; this audit supplies the first bounded definition. |
| Existing 0E definition | OBSOLETE / ABSENT | Repository planning and roadmap search found no 0E specification or allocated scope. |

No two current authorities materially conflict. The earlier 0D7-P report itself
requires reassessing product gaps after 0D6-D, which is what this audit does.

## 4. Current real capability map

| Chain stage | Current state | Evidence and boundary |
| --- | --- | --- |
| Project -> Timeline -> Branch -> Chapter | IMPLEMENTED; main-timeline continuation sealed | Shared lifecycle adapters delegate to `ChapterLifecycleService`; 0D6-D continuity services explicitly reject non-main transitions. |
| Version / source -> Narrative Turn -> Feasibility -> Confirm | IMPLEMENTED / SEALED | Simulator services bind project, timeline, branch, chapter, Canon, source and operation scope. |
| Compile -> Candidate -> Review -> Commit -> Completion | IMPLEMENTED / SEALED | Candidate/review/commit state is exposed by `SimulatorLoopStateService`; review and commit remain explicit operations. |
| Completion -> Successor -> next Turn | IMPLEMENTED / SEALED for main timeline | 0D6-C sealed the browser-visible progression loop; readiness and start remain scope-bound and fail closed. |
| Branch memory -> immutable transition snapshot | SEALED for main timeline | `BranchMemoryContinuityService` creates one immutable snapshot per transition. |
| Vector rebuild/cache -> scoped manifest | SEALED for main timeline | `VectorIndexLifecycle` binds a manifest to the verified snapshot and keeps vector data `REBUILDABLE_CACHE`. |
| Next-chapter prose continuity | PARTIAL / ADVISORY | `continuity_checker.py` compares only the previous tail and current head; it may call a configured model and otherwise uses a lexical fallback. |
| Chapter quality and refinement | IMPLEMENTED but PARTIAL / ADVISORY | `quality_checker.py` has local scores and an optional model evaluator; `draft_editor_refine.py` can make bounded edits. Evidence is not yet a single review-bound chapter-assembly record. |
| Traditional workflow | IMPLEMENTED, separate presentation | Traditional and Simulator lifecycle adapters share the same lifecycle service, while their interfaces and workflows remain distinct. |

## 5. Remaining capability inventory

| Candidate | Current state | User value | Authority readiness | Technical risk | Dependency | Regression cost | UX impact | Recommended priority |
| --- | --- | ---:| ---:| ---:| --- | ---:| --- | --- |
| Non-main timeline / branch continuation | NOT IMPLEMENTED | High long-term | Low | High | Timeline-safe lifecycle, memory, vector and recovery authority | High | Large | Deferred |
| Provider Live | Infrastructure exists; default-off | Medium | Partial | High external risk | Credential, consent, token counter, usage reconciliation and live validation | High | Targeted | Deferred |
| Simulator/workspace UX | Usable but developer/authority-oriented | Medium | Partial | Medium | Product design specification | High | Large redesign | Deferred |
| Narrative quality / chapter assembly | Local checks, optional model assessment, review gate and bounded refinement exist | High | High for an advisory, version-bound first slice | Medium | Existing version/review/continuity services | Medium | Targeted existing-review integration | **1** |
| Traditional / Simulator unification | Shared lifecycle, separate workflows | Medium | Low | High | Explicit product/UX decision | High | Large redesign | Deferred |
| Memory/vector/retrieval follow-up | Main continuity/recovery sealed | Medium | High for optimization only | Medium | Measurable retrieval-quality evidence | Medium | None initially | Deferred |

### Candidate findings

- **Non-main continuation:** not inferred from `timeline_id` fields. Both
  continuity capture and continuity-vector rebuild explicitly support only
  `main`; readiness also rejects non-main. It is a storage-authority project,
  not a UI toggle.
- **Provider Live:** the application has consent, budget, idempotency,
  cancellation/reconciliation contracts and a one-request adapter, but the UI
  capability is server-default-off. No live profile, real credential, or
  external call was inspected or used. It is not the shortest safe product
  improvement.
- **Simulator UX:** the current surface exposes branch registry, authority,
  immutable journal, candidate evidence, recovery and commit controls. It is
  appropriate for a simulator but too broad and information-architectural to
  redesign without a dedicated UX specification.
- **Quality:** a technically valid chapter can still be weak: current local
  checks are heuristic, the optional model evaluator is best-effort, continuity
  is a two-window comparison, and a human may force a low score through the
  review gate. These are appropriate as advisory mechanisms, but their
  freshness, source binding, coverage and hand-off are not one coherent
  chapter-assembly evidence contract.
- **Traditional/Simulator:** adapters prove common lifecycle semantics, but do
  not establish that the two authoring experiences should be merged. No merge
  is recommended from this evidence.
- **Memory/vector:** 0D6-D closed the main authority defect. Remaining items
  are retrieval quality, cache cost and context-selection optimization, not a
  reason to reopen its sealed source/cache classification.

## 6. Dependency analysis

| Candidate | What must exist | Does 0D6 provide it? | Separate blocker | Self-contained phase? |
| --- | --- | --- | --- | --- |
| 0D7 quality evidence | Version selection, explicit review/commit gate, continuity and quality evaluators | Yes; stable source/continuity boundary | No Provider requirement for deterministic baseline | Yes |
| Non-main continuation | Tuple-safe project/timeline/branch/chapter/canon/memory/vector/commit/successor authority | No | Major backend authority work | Not yet |
| Provider Live | Consent, credential governance, exact/conservative token accounting and external operational validation | Partly unrelated | Owner approval for live use | Not now |
| Workspace redesign | User research and a frontend specification | Not relevant | Design decision | Not safely |
| Retrieval optimization | Retrieval-quality metrics and bounded cost target | Main recovery yes | Product quality benchmark | Later |

The shortest path to meaningful writing value is therefore a quality-evidence
closure around the already-working review gate, rather than another
infrastructure expansion.

## 7. Recommended phase and invariant

**Why now:** 0D6 makes chapter-to-chapter state truthful. The next practical
bottleneck is whether the author receives enough trustworthy evidence to judge
the prose before that truthful state is committed and carried forward.

**First invariant:** every review-ready chapter has one immutable,
version-bound assembly-evidence record that reports the exact evaluated source,
quality/continuity coverage and freshness. It is advisory evidence; it neither
mutates prose nor becomes Canon, memory, commit, vector or automatic-approval
authority.

**Smallest production scope:** deterministic assembly evidence from existing
version, plan, continuity and quality inputs; stale/mismatched evidence fails
closed for display as review-ready; a targeted display in the existing review
surface; no new workspace.

**Exit condition:** an author can inspect an exact-version evidence summary,
understand absent/stale checks, and make an explicit human review decision.

## 8. Stage decomposition

| Slice | Objective | Allowed / prohibited | Authority boundary | Verification and exit | Browser |
| --- | --- | --- | --- | --- | --- |
| 0D7-P | This completed audit and brief | Planning records only; no implementation | Roadmap authority | One next phase and bounded brief | No |
| 0D7-A | Define and persist deterministic, version-bound assembly-evidence schema | Existing quality/continuity/version reads and focused service work; no Provider call, prose mutation or commit-policy relaxation | Derived, advisory evidence only | Freshness, source binding, missing/stale/corrupt fail-closed tests | No |
| 0D7-B | Present that evidence in the existing review path and retain explicit human decision | Targeted existing-review route/UI wiring; no workspace redesign or auto-approval | Human review remains commit authority | Existing review path shows exact evidence and safe unavailable state | Yes, focused |
| 0D7-FV | Verify quality evidence across draft/edited/manual and chapter transition boundaries | Verification only | No authority redesign | Focused plus affected regressions; browser only if B changes user-visible contract | Conditional |
| 0D7-SEAL | Reconcile evidence and seal or report blocker | Documentation/status only | No production change | Explicit owner seal decision | No |

## 9. Deferred work

- Multi-timeline continuation, only after its authoritative tuple is
  demonstrated storage-safe across commit, canon, memory, vector and successor.
- Provider Live, until an owner separately authorizes credential/consent,
  budget policy and real external-call validation; it remains default-off.
- Traditional/Simulator unification and any broad workspace redesign, pending a
  UX/Frontend Design Specification.
- Retrieval ranking/cost optimization, after quality measurements identify it as
  an actual writing bottleneck.

## 10. Model and cost plan

| Slice | Main model | Reasoning | Agent count | Role | Escalation condition |
| --- | --- | --- | ---: | --- | --- |
| 0D7-P | Terra | Medium | 1 | Roadmap authority audit | Conflicting current seal/planning authority |
| 0D7-A | Terra | Medium | 1 | Advisory-evidence service and tests | Source/version authority ambiguity |
| 0D7-B | Terra | Medium | 1 | Targeted review-surface integration | Browser contract or accessibility ambiguity |
| 0D7-FV | Terra | Medium | 1 | Bounded verification | Repeatable cross-boundary regression failure |
| 0D7-SEAL | Terra | Medium | 1 | Evidence reconciliation | Material conflict between FV and implementation evidence |

Sol is not the default for any slice. Browser ownership, if required, stays
with the single main agent.

## 11. Risks and next authorization

- Quality signals must remain advisory; only the existing explicit human review
  decision can permit a commit.
- Optional model evaluation must remain default-safe and failure-tolerant; the
  deterministic evidence baseline must not make Provider execution necessary.
- A UI change beyond the existing review surface triggers a separate design
  specification rather than ad-hoc workspace redesign.

**Next:** authorize `Phase 0D7-A` only, or request revision of this roadmap
decision. Do not start implementation automatically.
