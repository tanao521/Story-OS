# Phase 0D6-C-B-RC11

## Outcome

**PARTIALLY PASSED — RC12 REQUIRED.**

The canonical registry resolver and the Branch/Simulator compatibility path
are complete. Real Chromium then exposed a separate UUID/slug mismatch in the
sealed Narrative Turn and chapter-progression callers, so the delayed
GET/POST matrix cannot be accepted in RC11 without expanding into those
authorities.

## Owner Identity Decision

The external product `project_id` is the ProjectManager UUID. The existing
project directory name is `storage_project_id` and is used only by legacy
filesystem stores. It is not returned as the canonical browser/API identity.

## Resolver Architecture

`ProjectIdentityResolver` reads `ProjectManager.get_registered_project()`.
That adapter reads only `.story_os/projects.json`; it does not use project
directory discovery. Resolution validates one exact UUID record, a contained
existing root, matching registry and project metadata, matching slug, and
matching registered root.

Unknown, duplicate, malformed, missing, and inconsistent identities fail
closed. There is no UUID-as-path fallback, name lookup, directory scan,
automatic registration, reverse lookup, or HTTP resolver endpoint.

## No-Migration Boundary

Project directories, Branch registries, historical Turn paths, Candidate,
Review, Commit, and vector data are not migrated or rewritten.

## Branch and Simulator Compatibility

`BranchLifecycleService` now distinguishes canonical `project_id` from
`storage_project_id`. API scope and immutable operation authority retain the
UUID while `TimelineContext` addresses the existing slug-backed storage.

`SimulatorLoopStateService` validates and returns the canonical UUID while its
internal readers continue using the storage slug. Existing low-level callers
that intentionally pass the slug remain compatible.

## Same-Service Multi-Project and Sibling Branch

The browser fixture now creates Project A and Project B through
`ProjectManager.create_project()` in one registry and process. Project A
creates `main` and `sibling` through the production Branch lifecycle service.
No project registry or Branch registry is handwritten.

## Chromium Scope Matrix

Chromium loaded Project A by UUID and rendered both registered sibling
branches. Branch and Simulator routes retained the UUID externally.

The first full-matrix gate then failed before delayed races could be accepted:
Narrative Turn reported a scope mismatch and progression reported corrupt
authority because those sealed callers still compare the browser UUID with
the active directory slug. Traditional/project/branch delayed GET/POST,
history, normal start, and response-loss are therefore **not claimed**.

## Vector Regression Boundary

RC11 changes no vector namespace, embedding, manifest, Compiler, Review, or
Commit code. The RC10 contract remains `storyos_memory_ngram_v1`,
`storyos_repository_ngram`, version 1, dimension 512.

## Cleanup

The browser tab and server were closed. Both formal projects, sibling
branches, audit data, and the complete temporary workspace were removed.

## FV2 Gate

FV2 remains unauthorized. RC12 must add the same explicit compatibility
boundary to the Narrative Turn and chapter-progression callers without
changing sealed authority semantics, then rerun the full Chromium and RC10
clean-room matrices.

## RC12 Follow-Up

RC12 closed the Narrative Turn and chapter-progression UUID/storage caller
gap. Formal UUID DTO and operation scopes now pass. Chromium then exposed an
independent sibling-branch delayed GET stale-response defect, so the current
status is `PARTIALLY PASSED — RC13 REQUIRED`; FV2 remains unauthorized.

## Non-Goals

No project migration, registry rewrite, vector change, provider work,
dependency change, FV2 execution, or Owner Seal is included.
