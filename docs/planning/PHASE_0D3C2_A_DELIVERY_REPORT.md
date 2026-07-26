# Phase 0D3C2-A Delivery Report

**Final result: PASSED.** Server hardening closes every 0D3C2-P blocker while
the production UI remains Mock-only.

## Required answers

| Topic | Delivered behavior |
| --- | --- |
| Live project scope | New Live routes resolve only a valid project-manager `project_key`; state-derived project/timeline binds ticket scope. |
| `project_root` | Rejected for every Live-capable entry. Legacy routes reject Live before any legacy path selector is used. |
| Consent | Server-issued immutable ticket carries safe scope, source/context fingerprints, ordered Personas, profile/revision, budget, expiry, opaque idempotency key, and consent text version. |
| Expiry | Five minutes; expired consent cannot reserve ownership or call a provider. |
| Idempotency | Ticket key + canonical fingerprint are atomically reserved with exclusive file creation before provider work. |
| Duplicate/concurrent/lost response | One fake-provider call; duplicate sees existing `in_progress`/final status; recovery returns the same final panel id. |
| Public force | Forbidden from new Live schema; old direct Live routes are rejected. |
| Budget/cost | Call/output/input/total caps and timeout are server owned; exact provider input count is required. Cost is explicitly unavailable with null amount/currency, not fabricated zero. |
| Timeout/cancel/reconciliation | Adapter timeout is profile-bound; pre-start cancel is final, in-progress cancel is only a request, and uncertain interrupted ownership is reconciliation-required with no retry. |
| Source race | Consent hash is rechecked before reservation and before each child call. Changed source yields `SOURCE_CHANGED_AFTER_CONSENT`; later child calls do not start. |
| Audit | Immutable ticket and append-only attempt audit preserve safe metadata only; mutable ownership is limited to idempotency coordination. |
| Redaction | Public profile/status/audit/ticket exclude endpoint, secret, env name, prompt, chapter text, raw response/exception, and absolute path. Sentinel test proves persistence redaction. |
| Mock UI | Unchanged. No Live control, no credential input, and no automatic retry/fallback were added. |

## Validation

Executed from `story-os-demo`:

```text
python -m pytest -q tests/test_phase0d3c2a_live_hardening.py tests/test_phase0d3c2_preflight.py tests/test_phase0d2b1_model_persona_execution.py tests/test_phase0d2b2_model_persona_panel_execution.py tests/test_phase0d2b3_panel_review_model.py tests/test_web_routes.py
129 passed in 10.46s
```

The 0D3C2-A focused suite adds consent/no-run proof, profile projection,
sequential/concurrent idempotency, response-loss recovery, expiry/registry
drift, source-before/source-during execution, budget, failure redaction,
reconciliation, cancellation, and socket network-canary coverage.

`python -m compileall -q core system web` and the relevant four static
`node --check` commands passed. Existing Mock/Review/Context route and frontend
tests are included in the focused suite.

The repository has pre-existing unrelated whitespace findings in dirty files;
no whitespace warning was introduced by this phase.

## Protected data

All test writes were confined to `tmp_path` projects. The final protection
check confirms Chroma **6/6** baseline match, authority assets **16**, Obsidian
bindings **30**, and real model/panel Run JSON **0/0**. No real Provider,
network, or token activity occurred.

## Delivery

See the four new security documents, updated contract/UI documents, and the API
note in `story-os-demo/README.md`. The next possible phase is separately
authorized 0D3C2-B; this task stops without entering it.
