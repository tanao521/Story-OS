# Review design fixtures

These redacted fixtures are derived from `ModelPersonaPanelReview.to_dict()` and the 0D2B3 state/selection tests. They are design-only data, not run-store records. They use safe ids, contain no prompts, chapter text, secrets, endpoints, absolute paths, or raw exceptions, and must never be copied to either `data/simulator/model_persona_runs` or `data/simulator/model_persona_panel_runs`.

| Fixture | Coverage |
|---|---|
| ready-current | ready, completed, current, complete usage |
| ready-cached | ready, cached child state |
| partial | partial, partially completed, missing/blocked persona |
| not-run | not_run, no selected run |
| failed | failed, provider_failed |
| stale-mixed | stale, mixed child staleness |
| source-missing | source_missing |
| agreements-conflicts | agreements and unresolved conflicts together |
| usage-null | `usage_summary: null` |
| warnings-multiple | multiple structured warnings |
| explicit-run-404 | safe 404 envelope; context retained by the prototype |

The prototype loads these files from this directory when served by a local static server. The state switcher is clearly marked Design Preview and has no production API or write path.
