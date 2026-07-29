# Phase 0D6-C-B-RC1 — Post-Start Successor Convergence

## Purpose

Repair the FV successor convergence defect without changing sealed backend authority.

## FV Defect and Root Cause

After a valid start rebind, the progression module treated the successor URL chapter as a new completed previous chapter and issued readiness. The sealed backend correctly returned `BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE`, but the UI obscured the active successor Turn.

## Readiness Ownership Contract

The sealed readiness route remains the completion authority. The Simulator read model only decides whether the current scope already has an active Turn. Progression reads readiness only for a matching Simulator scope with no active Turn; an active successor Turn releases progression ownership.

## Post-Start, Replay, and Existing-Turn Convergence

`handoffToSuccessor()` is the single rebind helper used by validated POST success, durable replay success, and Existing Turn continuation. It records only an in-memory, scope-and-Turn-bound handoff, aborts old readiness, and rebinds to the server-returned successor Turn. A reloaded page derives the same release from the authoritative Simulator read model.

## Reload and Navigation

Reloading an `awaiting_action` successor loads the existing Turn and suppresses next-next readiness. Back may read the completed previous chapter and expose its existing Turn; returning to the active successor remains non-interfering.

## Isolation and Boundaries

The handoff is bound to project, timeline, branch, chapter, Turn identity, and epoch. Traditional mode clears module state and sends no progression request. No timeout, URL arithmetic, local/session storage, or backend change is used.

## Production Change Boundary

- `web/static/simulator-chapter-progression.js`: ownership guard and shared handoff helper.
- `web/templates/index.html`: cache-buster only, so Chromium receives the updated module.
- No backend, schema, route, service, dependency, or configuration change.

## Browser Regression Matrix

The focused Chromium run verifies normal start, successor convergence, reload, and Existing Turn continuation. Response-loss replay, later-completion reactivation, and full Traditional/context isolation remain for FV2 verification.

## FV2 Gate and Non-Goals

Do not enter FV2 from this RC. No new product feature, sealed-authority alteration, automatic start, automatic confirm, or non-main timeline behavior is included.
