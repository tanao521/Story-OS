# ModelPersonaPanelReview → UI mapping

The response is consumed as read-only JSON. `authoritative_panel` and each card's `authoritative` object are the source of truth; `model_supplement` is visibly secondary and never overwrites authoritative values.

| Contract area | Type/nullable | UI treatment | Empty/unsafe handling |
|---|---|---|---|
| `schema_version`, `evaluator_version` | string | compact diagnostic metadata | hide from primary hierarchy |
| `project_id`, `timeline_id`, `chapter_id`, `source_version_id` | string/int; source nullable | ReviewHeader context chips | missing source shows source-missing state |
| `review_status`, `selected_run_status`, `selected_run_staleness` | enum/string; selected values nullable | ReviewStatusBanner + SelectionSummary | label exact enum; never imply ready |
| `summary`, `selection_reason` | object/string | header summary and “why selected” disclosure | escape text; preserve reason |
| `authoritative_panel` | object | AuthoritativePanelSummary | display fixed authority/order; no model merge |
| `persona_reviews[]` | ordered cards | PersonaReviewCard | preserve `persona_order`; absent cards are missing, not zero |
| card `authoritative` | object | score/risk/flags/weight/rank block | format numbers; keep flags and evidence refs separate |
| card `model_supplement` | object | secondary model feedback block | nullable usage stays null; redact provider details beyond identifiers |
| `agreement_groups[]` | list | AgreementGroupList | empty means “暂无一致项”, not failure |
| `conflict_groups[]` | list, unresolved | ConflictGroupList with unresolved badge | no auto-resolution or write action |
| `evidence_summary` | object | EvidenceSummary counts/coverage | do not render chapter text or raw paths |
| `execution_summary` | object | ExecutionSummary counters | show expected vs actual calls as audit facts |
| `usage_summary` | object or null | UsageSummary | null = “未提供用量”，never recompute |
| `staleness_summary` | object | StalenessSummary and stale ids | stale is warning/state, never auto-rerun |
| `warnings[]` | ordered strings/codes | StructuredWarningList | fixed severity order; safe labels only |

Suggested component tree: `SimulatorModeShell → ReviewHeader, ReviewStatusBanner, SelectionSummary, AuthoritativePanelSummary, PersonaReviewCard* → AgreementGroupList, ConflictGroupList, EvidenceSummary, ExecutionSummary, UsageSummary, StalenessSummary, StructuredWarningList`. Loading skeleton and API error boundary wrap the whole view; Empty/Failed/SourceMissing containers replace data regions as appropriate.

All text is escaped, status uses text/icon plus color, accordions are keyboard operable, and cards collapse to one column on narrow screens.
