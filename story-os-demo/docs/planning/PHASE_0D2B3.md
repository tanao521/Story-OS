# Phase 0D2B3 — Deterministic Panel Review Model

Phase 0D2B3 adds the read-only data contract consumed by a future simulator
front end. It selects an existing model Persona Panel Run, associates it with
the deterministic Reader Persona Panel, and exposes deterministic summaries.

## Gate and scope

The Phase 0D2B2 gate is a prerequisite: 1263 collected, 1258 passed, 5
skipped, 0 failed, 0 errors, and compileall passed. The RC3-IBR Chroma
baseline, 16 authority assets, and 30 Obsidian bindings remain protected.

This phase may add contracts, a read-only service, tests, CLI query support,
GET API support, and documentation. It does not call a model, synthesize a
panel, rerun or repair a model result, modify Persona order or authoritative
scores, write story assets, create runs, refresh caches, or write Chroma or
Obsidian.

## Deterministic data flow

```text
Reader Simulation Snapshot
  -> authoritative Reader Persona Panel Run
  -> saved Model Persona Panel Run
  -> saved child Persona Runs
  -> saved grounding/evidence reports
  -> ModelPersonaPanelReview
```

`ModelPersonaPanelReviewService` only reads existing stores and computes
in-memory projections. It does not call `ReaderSimulatorService.run_simulation`
or any Provider. It uses the existing child-run grounding and staleness
contracts rather than introducing a second validator.

## Run selection

Selection is scoped to the current project, timeline, chapter, and optional
source version. The priority is:

1. Explicit `panel_execution_id`.
2. Current completed run.
3. Current partially-completed run.
4. Current fallback run.
5. Latest stale run.
6. `not_run` when no eligible run exists.

Unknown or cross-scope explicit IDs return `PANEL_RUN_NOT_FOUND`/HTTP 404. A
failed run is not preferred over a usable completed or partial result.

## Contract boundary

`ModelPersonaPanelReview` contains:

- `review_status`: `ready`, `partial`, `not_run`, `failed`, `stale`, or
  `source_missing`;
- selection metadata: `selection_reason`, selected execution ID, run status,
  and run staleness;
- an `authoritative_panel` section and a separate `model_supplement` section;
- stable `persona_reviews` in authoritative Persona order;
- `agreement_groups` and `conflict_groups`;
- evidence, execution, usage, staleness, and structured warning summaries.

Authoritative data includes Persona identity, order, score, risk, flags, weight,
rank, and status. Model supplements include feedback, evidence references,
grounding status, model run status, cache status, execution profile, provider
and model identity, saved usage, and child staleness. Model fields never
overwrite or flatten into authoritative fields.

## Agreement and conflict rules

Agreement is created only from exact structured keys: the same authoritative
flag code or the same evidence ID must occur for at least two Personas. No
natural-language similarity, embedding, or model judgment is used.

Conflicts are emitted for exact structured comparisons, including severity,
evidence, and retention-risk-band differences for a shared flag code. Every
conflict has `resolution_status: unresolved`; no weighting, majority vote, or
automatic resolution is performed.

## Evidence, usage, and staleness

Evidence counts come from saved child grounding reports and saved evidence
references. No chapter正文 is returned. Usage is copied from the saved Panel
Run; missing values remain `null` and `usage_completeness` is preserved.

Staleness is read-only. Current source/context/evaluator/persona/provider
fingerprints are compared with the saved panel and child fingerprints. The
aggregate is `current`, `partially_stale`, `stale`, `source_missing`, or
`not_run`. A query cannot create a replacement result.

## Interfaces

CLI:

```text
show-reader-persona-panel-review
```

Examples:

```powershell
python main.py show-reader-persona-panel-review --chapter 1 --json
python main.py show-reader-persona-panel-review --chapter 1 --panel-execution-id <id>
```

GET API:

```text
GET /api/reader-persona/model-panel/review?chapter_id=1
GET /api/reader-persona/model-panel/runs/{panel_execution_id}/review
```

Both interfaces are project/timeline scoped, return stable JSON, omit prompts,
chapter正文, secrets, full endpoints, absolute paths, and internal exception
text, and return 404 for an unknown run.

## Front-end readiness

The response is intentionally data-only. A future simulator front end can
render `summary`-equivalent selection metadata, `persona_reviews`, agreement
and conflict groups, evidence, execution, usage, staleness, and warnings
without re-associating runs or reimplementing business rules. No visual style
fields, React/Vue code, CSS, or page behavior is part of this phase.
