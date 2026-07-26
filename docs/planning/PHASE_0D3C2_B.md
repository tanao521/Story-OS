# Phase 0D3C2-B — Read-only Live Plan & Consent UI

## Result

**PASSED AND SEALED after B-FIX.** The Simulator now exposes a visually distinct, read-only Live Plan
and Consent surface. It can load safe public profiles and Persona options and,
after explicit user confirmation, create a server-owned consent ticket. It
cannot execute, retry, or recover a Live Run.

## Scope delivered

- Added the isolated `simulator-live-consent.js` module and responsive scoped
  styles in the existing Simulator review surface.
- Reused the Context Navigator projection and invalidated/aborted all private
  UI state on project, timeline, chapter, source, Back, or Forward changes.
- Added safe profile readiness and server-owned budget projections. Profiles
  without an exact input-token counter remain blocked with
  `INPUT_TOKEN_BUDGET_UNAVAILABLE`.
- Added explicit consent checkbox, server-order Persona selection (1–5),
  lower-only requested call cap, retry `0`, fallback `none`, and truthful
  unavailable cost copy.
- Consent request body is limited to `project_key`, `chapter_id`, optional
  `source_version_id`, `persona_ids`, `profile_id`, `max_provider_calls`, and
  `consent_text_version`.
- Full ticket and idempotency values remain closure-memory only. The UI shows
  only a shortened ticket id, status, expiry, safe scope, ordered Personas,
  and the explicit no-execution result.
- The production frontend contains no Live Run endpoint and no credential,
  endpoint, source text, path, storage, clipboard, or console handling.
- B-FIX closes Consent state integrity: the entry button requires an
  authoritative context-ready projection, selection changes invalidate old
  tickets, expiry is timer-backed and server-time authoritative, and a
  successful ticket requires fresh confirmation before another submission.

## Safety boundary

No Provider, network model request, token counter call, Live Run, retry,
fallback, story/Canon/Summary write, Chroma/Obsidian operation, user-project
automated acceptance write, dependency installation, commit, push, reset,
clean, or rebase was performed. Mock semantics remain unchanged.

## Validation

- 0D3C2-B focused frontend contract tests: passed.
- 0D3C2-A hardening, 0D3C2 preflight, 0D3B1 frontend, and web-route tests:
  passed.
- Node syntax check and compileall: passed.
- Browser smoke: not run; no browser dependency was installed and screenshots
  are not a gate for this phase.

## Stop rule

0D3C2-B is complete. Stop here. Do not enter 0D3C2-C.
