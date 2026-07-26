# Phase 0D3C4-B1-FIX Delivery Report

## Final status

- Phase 0D3C4-B1-FIX: **PASSED**
- Phase 0D3C4-B1 sealing status: **SEALED**
- Production Live: **DEFAULT-OFF**
- Real Profile Activation: **BLOCKED BY EXTERNAL ASSET/COMPLIANCE GATE**
- Canary: **NOT AUTHORIZED**
- B2: **NOT ENTERED**
- Real Provider/network/credential/token/cost: **0**

## Start-before baseline (B1-FIX independent verification input)

The independent verification concluded B1 was **PARTIALLY PASSED — FIX
REQUIRED**.  The focused B1 test suite before this FIX run produced:

```
61 passed, 2 skipped in 5.27s
```

Skips: file and directory symlink tests where the current Windows account
cannot create symlinks.

Identified gaps (problem → root cause):

| # | Gap | Root cause |
| --- | --- | --- |
| 5.1 | Path-escape test coverage insufficient | Record-ID grammar was secure, but tests missed UNC, multi-layer `../../`, similar-prefix, and canonicalization-escape cases |
| 5.2 | No record contract version field | `ProviderUsageReconciliation` lacked a `record_version` field; unknown versions could not be rejected |
| 5.3 | Reconciliation write non-atomic | Store used `open("x")` directly without temp-file + fsync + atomic link |
| 5.4 | Evaluator boundary tests incomplete | Missing explicit fail-closed tests for empty payload, missing thinking/response_format, NaN counter, internal exceptions, etc. |
| 5.5 | Dependency scan was string-matching only | No AST-based scanner; alias imports, dynamic imports, and comment false-positives were not handled |
| 5.6 | Documentation stale | Delivery report lacked start-before baseline; README did not mention B1/B1-FIX |

## Root-cause and fix matrix

| Problem | Root cause | Modified file | Fix | Test evidence |
| --- | --- | --- | --- | --- |
| 5.1 Path escape | Tests missing UNC/multi-layer/canonicalization cases | `tests/test_phase0d3c4b1_conservative_budget.py` | Added parametrized escape variants and canonicalization tests | `test_reconciliation_store_rejects_path_escape_variants`, `test_reconciliation_store_rejects_canonicalized_escape`, `test_reconciliation_store_accepts_similar_prefix_id` |
| 5.2 Contract version | No `record_version` field | `system/provider_usage_reconciliation.py` | Added `record_version` field with `RECONCILIATION_RECORD_VERSION="1"` and validation against supported versions | `test_reconciliation_rejects_unknown_record_version`, `test_reconciliation_rejects_non_string_record_version`, `test_reconciliation_rejects_empty_record_version`, `test_reconciliation_rejects_mismatched_revision_identity`, `test_reconciliation_rejects_malformed_canonical_fingerprint`, `test_reconciliation_rejects_bool_int_confusion` |
| 5.3 TOCTOU/JSON integrity | Non-atomic write | `system/provider_usage_reconciliation.py` | Replaced `open("x")` with temp-file + `flush` + `os.fsync` + `os.link` (atomic, fails if target exists) + cleanup in `finally` | `test_reconciliation_write_is_atomic_and_durable`, `test_reconciliation_write_failure_preserves_existing`, `test_reconciliation_write_does_not_leave_partial_target`, `test_asset_toctou_single_read_provides_consistent_bytes`, `test_asset_rejects_truncated_json_during_read`, `test_asset_hash_is_computed_from_consumed_bytes` |
| 5.4 Evaluator fail-open | Missing boundary tests | `tests/test_phase0d3c4b1_conservative_budget.py` | Added 14 explicit fail-closed tests for empty payload, missing messages, unknown provider/model, missing thinking/response_format, counter revision mismatch, exact counter, negative limit, overflow, internal exception, NaN, non-list messages, non-dict message, missing JSON keyword | `test_evaluator_empty_payload_fails_closed` through `test_evaluator_missing_json_keyword_fails_closed` |
| 5.5 Dependency scan | String matching only | `system/conservative_dependency_scan.py` (NEW), `tests/test_phase0d3c4b1_conservative_budget.py` | Implemented AST-based scanner using `ast.parse` and `ast.walk`; detects plain/aliased/from imports, dynamic imports, non-literal dynamic imports; reports file+line+module; handles BOM; fails closed on unparseable files | `test_scan_source_detects_plain_import` through `test_scan_finding_has_file_and_line` (16 tests) |
| 5.6 Documentation | Stale facts | This report, `PHASE_0D3C4_B1_FIX.md`, `PHASE_0D3C4_B1.md` | Added start-before baseline, root-cause matrix, accurate test counts, security boundary confirmation | See validation section below |

## File changes

| File | Purpose | Type |
| --- | --- | --- |
| `story-os-demo/system/provider_usage_reconciliation.py` | Added `record_version` field + validation; atomic write via temp+fsync+os.link | Production |
| `story-os-demo/system/conservative_dependency_scan.py` | NEW: AST-based dependency scanner | Production |
| `story-os-demo/tests/test_phase0d3c4b1_conservative_budget.py` | Added 54 new security closure tests | Test |
| `docs/planning/PHASE_0D3C4_B1_FIX_DELIVERY_REPORT.md` | This report with start-before baseline | Documentation |
| `docs/planning/PHASE_0D3C4_B1_FIX.md` | Updated scope description | Documentation |
| `docs/planning/PHASE_0D3C4_B1.md` | Updated sealing status | Documentation |

## Validation results

All commands executed from `story-os-demo/` with
`PYTHONPYCACHEPREFIX` set to a temporary directory.

### 1. B1-FIX focused tests

```
python -m pytest tests/test_phase0d3c4b1_conservative_budget.py -q
```

Result: **115 passed, 2 skipped** — exit code 0.

Skips: symlink tests where Windows does not grant symlink creation
privileges.

### 2. Python compile check

```
python -m compileall system/provider_usage_reconciliation.py system/conservative_dependency_scan.py
```

Result: **exit code 0**.

### 3. Combined regression (B1 + B0 + C3 + C2 + provider/panel/review/web)

```
python -m pytest tests/test_phase0d3c4b1_conservative_budget.py tests/test_phase0d3c4b0_conservative_policy_simulation.py tests/test_phase0d3c2a_live_hardening.py tests/test_phase0d3c2b_live_consent_frontend.py tests/test_phase0d3c2c_live_run_frontend.py tests/test_phase0d3c2rc_live_safety_closure.py tests/test_phase0d3c3_provider_readiness.py -q
```

Result: **174 passed, 2 skipped** — exit code 0.

The 2 skips are symlink-creation tests on Windows accounts without
symlink privileges; runtime rejection of symlinks remains enforced.

## Security boundary confirmation

- Provider calls: **0**
- Provider network requests: **0**
- Real tokens: **0**
- API/provider cost: **0**
- Real tokenizer asset: **not provisioned**
- Production Live: **not enabled (DEFAULT-OFF)**
- Canary: **not entered (NOT AUTHORIZED)**
- B2: **NOT ENTERED**

## Git status

B1-FIX scope files (all untracked new files in the current worktree,
produced during this FIX run):

- `story-os-demo/system/provider_usage_reconciliation.py` — new production code (modified in place during this FIX run; file is untracked in git)
- `story-os-demo/system/conservative_dependency_scan.py` — new production code
- `story-os-demo/tests/test_phase0d3c4b1_conservative_budget.py` — new test code (extended with 54 security closure tests)
- `docs/planning/PHASE_0D3C4_B1_FIX_DELIVERY_REPORT.md` — new documentation (this report)
- `docs/planning/PHASE_0D3C4_B1_FIX.md` — new documentation
- `docs/planning/PHASE_0D3C4_B1.md` — new documentation

Untracked files unrelated to B1-FIX: preserved as-is.  The worktree
contains a large number of pre-existing dirty/untracked files from
prior phases (0D3A/B/C1/C2/C3/C4-A0/C4-B1 and others); these were not
created, modified, rolled back, or committed by this FIX run.

`git diff --stat` against the last commit only reflects tracked-file
modifications belonging to those prior phases; B1-FIX produced no
tracked-file modifications.

No commit or push was performed unless explicitly authorized by the user.

## Remaining limitations

- A real Layer-A asset is not present and its compliance/license Gate
  remains unresolved.
- Symlink-specific tests may skip where Windows does not grant symlink
  creation privileges; runtime rejection remains implemented.
- Production Live and Canary remain unauthorized.
- B2 has not been entered.

## Post-FIX RC verification

A subsequent B1-FIX-RC independent verification pass discovered and fixed
one additional issue in `append()`: `self.root.resolve(strict=True)` was
not wrapped in `try/except OSError`, meaning a root-directory resolve
failure (permission error, reparse-point failure, etc.) would escape as a
raw `OSError` instead of a structured `PATH_NOT_CONTAINED` error. This was
a fail-*unsafe* error path — the operation still didn't succeed, but the
error type was not the expected domain error.

RC also added 6 deterministic symlink safety decision tests (via
monkeypatch) that never skip, complementing the 2 real-symlink integration
tests that may skip on Windows without symlink privilege.

RC final focused count: **121 passed, 2 skipped**.
RC full regression: **392 passed, 2 skipped**.

See `PHASE_0D3C4_B1_FIX_RC.md` for the full independent verification report.

## Conclusion

Phase 0D3C4-B1-FIX: **PASSED — ACCEPTED after RC**
Phase 0D3C4-B1: **SEALED**

B1 is ready for sealing. Whether to enter B2 still requires separate OWNER
authorization.
