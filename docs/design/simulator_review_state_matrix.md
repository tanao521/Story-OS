# Simulator review state matrix

| Review/run/data condition | User-facing meaning | Persona cards | Regions and next read-only step | Forbidden implication |
|---|---|---|---|---|
| ready + completed/current | Review ready | show all ordered cards | show all summaries; inspect evidence/conflicts | never present model supplement as authority |
| ready + cached | Current cached result | show cards with cached badge | show cache metadata | do not suggest a fresh run occurred |
| partial / partially completed | Some personas completed | show completed cards; mark missing/blocked | show execution counters and warnings | no “all personas passed” |
| not_run / no selected run | No review run selected | hide score cards or show not-run placeholders | explain selection; choose chapter context only | no rerun button |
| failed / provider failure | Run failed | show only safe retained data, otherwise placeholders | error boundary + provider-failure warning | do not expose raw exception/endpoint |
| stale / child stale | Source or child result is stale | show cards with stale badges | staleness summary first; inspect only | no automatic rerun |
| source_missing | Source version unavailable | do not show authoritative scores as current | source-missing explanation | no fabricated scores |
| mixed staleness | Current and stale children coexist | show per-card status | panel-level warning plus stale ids | no flattening to ready |
| usage complete | Full usage exists | unchanged | show input/output/total/duration | no recalculation |
| usage partial or null | Usage incomplete/unavailable | unchanged | show incomplete or “not provided” | never display zero as measured |
| no agreement groups | No detected agreement | unchanged | explicit empty state | not an error |
| no conflict groups | No detected conflict | unchanged | explicit empty state | not “conflicts resolved” |
| evidence missing/invalid | Evidence coverage is incomplete | show safe cards | evidence warning and counts | no chapter text |
| warnings present | Structured caution | unchanged | warnings above detail sections | do not hide warnings |
| explicit run selected | User requested execution id | show selected run | show selection reason/id | no silent fallback |
| automatic selection | Service selected current/fallback | show selected run | show exact selection reason | do not imply user selection |
| unknown explicit id (404) | Requested run not found | none | API error boundary with retry-free navigation back | no guessed run |

Each state retains project/timeline/chapter URL context. All actions are navigation or disclosure only.

## Safe fixture design

Keep fixtures inline in docs/tests or a future frontend-dev-only directory; never write real run directories. Use redacted ids (`proj-demo`, `timeline-demo`, `exec-demo`), no prompt, chapter text, secret, endpoint, absolute path, or raw exception. Required fixture variants: ready, partial, not_run, failed, stale, source_missing, agreements+conflicts, `usage_summary: null`, multiple warnings, and explicit-run-404 (error envelope only).
