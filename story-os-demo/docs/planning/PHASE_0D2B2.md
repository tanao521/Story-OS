# Phase 0D2B2: Bounded Multi-Persona Panel Execution

This phase adds an auditable orchestration layer around the existing
single-Persona model execution service. The deterministic Reader Persona Panel
remains the authority for scores, risk, flags, and ordering; model responses are
stored only as independent Persona supplements.

## Contract and limits

- `persona_ids` is a non-empty list of enabled registered IDs, with a hard
  server-side maximum of five. Duplicates and unknown IDs are rejected.
- Ordering is deterministic (`ReaderPersonaRegistry`/Phase 0D2A lexical
  authority), never the caller's ordering.
- `mock` and `live` are the only modes. Live execution additionally requires
  explicit `allow_model_call`, a registered configured profile, and a budget.
- `max_provider_calls` defaults to `1` and is bounded to `0..5`. A plan counts
  every live cache miss before execution. If it exceeds the budget, execution is
  globally blocked and makes zero live provider calls.
- Calls are strictly sequential. There is no parallelism, retry, fallback,
  repair request, merged prompt, moderator, or panel-synthesis model call.

## Data and cache

`POST /api/reader-persona/model-panel/plan` is read-only: it builds a compact
deterministic snapshot, checks the existing child-run fingerprints, and never
creates a child/panel run or calls a provider. Child caching is the existing
single-Persona cache; there is no broad panel cache.

Each `run` creates one immutable panel record under
`data/simulator/model_persona_panel_runs/`. The record has separate
`authoritative_panel` and `model_persona_runs` sections, child IDs/statuses,
fingerprints, call counts, usage completeness, and staleness state. It contains
no prompt, chapter text, provider request/response, credentials, endpoint, or
absolute path.

Usage counts only new live calls in the current panel run. Cache hits add no
token usage. With no live call, usage is `null` and completeness is
`not_applicable`.

## Interfaces

CLI commands:

```text
plan-reader-persona-model-panel
run-reader-persona-model-panel
list-reader-persona-model-panel-runs
show-reader-persona-model-panel-run
```

`--persona` is repeatable. Example:

```powershell
python main.py run-reader-persona-model-panel --chapter 1 --persona hook_driven_reader --persona world_logic_reader --mode live --execution-profile default --allow-model-call --max-provider-calls 2
```

Web endpoints:

```text
POST /api/reader-persona/model-panel/plan
POST /api/reader-persona/model-panel/runs
GET  /api/reader-persona/model-panel/runs
GET  /api/reader-persona/model-panel/runs/{panel_execution_id}
```

The phase does not modify story assets, Canon, Summary, Chroma, Obsidian,
selection state, or deterministic scoring.
