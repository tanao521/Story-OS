# Phase 0D6-B-RC3 Broad Failure Manifest

Execution date: 2026-07-28. Command: `python -m pytest -q --tb=no` in
`D:/novel/StoryOS/story-os-demo`.

Final result: **2281 passed, 52 failed, 7 skipped, 43 warnings** (exit 1,
471.64s). FV2 was 2299/34/7; the historical record is count-only 2239/33/7.
No historical node-id manifest, JUnit XML, or timestamped pytest log matching
2239/33/7 was found. The current `.pytest_cache/lastfailed` was not treated as
historical evidence.

Classification: A deterministic unrelated/pre-existing; B flaky; C concrete
environment-dependent; D 0D6-B regression; E attribution uncertain.

## Complete failure list

| Node ID | Domain/type | Reproduction | Modified-path reachability | Relation | Class/disposition |
|---|---|---|---|---|---|
| `tests/test_creative_loop.py::test_reflection_health_and_issues_bind_active_canon` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_proposal_needs_author_decision_and_does_not_change_plan` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_experiment_selection_never_rewrites_canon` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_strategy_outcome_is_correlational_and_handles_missing_data` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_chapter_reflection_job_is_bound_to_its_project` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_creative_loop_status_machine_audit_and_cache` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_health_reports_sources_missing_dimensions_and_standard_cost_profile` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_creative_loop.py::test_creative_loop_data_is_project_scoped` | creative-loop/assertion | broad | no | unrelated | A baseline |
| `tests/test_memory_repair_service.py::test_quality_report_is_bound_to_active_canon` | memory/assertion | broad | no | unrelated | A baseline |
| `tests/test_phase0b2_dual_project_isolation.py::TestAnalyticsIsolation::test_story_spec_isolation` | analytics/isolation | broad | no | unrelated | A baseline |
| `tests/test_phase0b2_dual_project_isolation.py::TestAnalyticsIsolation::test_chapter_analytics_isolation` | analytics/isolation | broad | no | unrelated | A baseline |
| `tests/test_phase0b2_dual_project_isolation.py::TestAnalyticsIsolation::test_market_analytics_isolation` | analytics/isolation | broad | no | unrelated | A baseline |
| `tests/test_phase0b2_dual_project_isolation.py::TestNoCrossProjectPollution::test_cwd_independence` | analytics/isolation | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc.py::TestVectorHealthyStateFix::test_rebuild_failure_healthy_false` | vector/assertion | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc.py::TestVectorHealthyStateFix::test_rebuild_failure_records_last_error` | vector/assertion | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc.py::TestCLIFix::test_clone_project_help` | CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c2_rc.py::TestCLIFix::test_clone_project_no_source_error` | CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c2_rc.py::TestCLIFix::test_clone_project_no_name_error` | CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c2_rc2.py::TestVectorStateWarningPropagation::test_rebuild_success_state_write_failure_reports_warning` | vector/warning | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc2.py::TestVectorStateWarningPropagation::test_rebuild_failure_state_write_failure_reports_both_warnings` | vector/warning | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc2.py::TestWindowsReparsePointGuard::test_no_links_allows_clone` | filesystem/assertion | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc2_vr.py::TestStaticExceptionPass::test_vector_state_update_failure_propagates_as_warning` | vector/warning | broad | no | unrelated | A baseline |
| `tests/test_phase0c2_rc2_vr.py::TestRealCLISubprocess::test_cli_help_displays_options` | CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c2_rc2_vr.py::TestRealCLISubprocess::test_real_cli_clone_success` | CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c2_vr_verification.py::TestVectorSyncOperation::test_clone_operation_stored_in_target` | vector/assertion | broad | no | unrelated | A baseline |
| `tests/test_phase0c3a_obsidian_cli.py::TestObsidianBindCLI::test_bind_success` | Obsidian CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3a_obsidian_cli.py::TestObsidianBindCLI::test_bind_with_timeline` | Obsidian CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3a_obsidian_cli.py::TestObsidianUnbindCLI::test_unbind_not_found` | Obsidian CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3a_obsidian_cli.py::test_cli_help` | Obsidian CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c3b_mirror_sync.py::TestCLIMirrorSync::test_cli_dry_run_bound_project` | mirror CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3b_mirror_sync.py::TestCLIMirrorSync::test_cli_sync_creates_files_and_manifest` | mirror CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3b_mirror_sync.py::TestCLIMirrorSync::test_cli_dry_run_unbound_project` | mirror CLI/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3b_mirror_sync.py::TestCLIMirrorSync::test_cli_help_flags` | mirror CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0c3c_obsidian_pull.py::TestCLIObsidianPull::test_cli_pull_scan_zero_write` | Obsidian pull/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3c_obsidian_pull.py::TestCLIObsidianPull::test_cli_pull_preview` | Obsidian pull/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3c_obsidian_pull.py::TestCLIObsidianPull::test_cli_pull_apply_requires_expected_hash` | Obsidian pull/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3c_obsidian_pull.py::TestCLIObsidianPull::test_cli_pull_unbound_exit_code` | Obsidian pull/subprocess | broad | no | unrelated | C Windows subprocess/locale |
| `tests/test_phase0c3c_obsidian_pull.py::TestCLIObsidianPull::test_cli_pull_help` | Obsidian pull/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d1_reader_simulator.py::TestCLI::test_simulate_reader_cli` | reader CLI/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d1_reader_simulator.py::TestCLI::test_simulate_reader_cli_help` | reader CLI/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d1_reader_simulator.py::TestCLI::test_list_reader_simulations_cli` | reader CLI/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d1_reader_simulator.py::TestCLI::test_cli_no_absolute_paths` | reader CLI/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d2a_reader_persona_panel.py::TestCLI::test_list_reader_personas_cli` | reader persona/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d2a_reader_persona_panel.py::TestCLI::test_run_reader_panel_cli` | reader persona/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d2a_reader_persona_panel.py::TestCLI::test_list_reader_panels_cli` | reader persona/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d2b1_model_persona_execution.py::TestCLISubprocess::test_help_success` | model persona/TypeError | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d2b1_model_persona_execution.py::TestCLISubprocess::test_cli_no_absolute_path_output` | model persona/subprocess | broad | no | unrelated | C Windows CLI path |
| `tests/test_phase0d4d_rc1.py::test_result_first_writer_wins_two_services` | narrative concurrency/assertion | 5 isolated failures | yes: narrative initial-turn lock | indirect | E owner review |
| `tests/test_phase0d4e2_memory_concurrency.py::test_same_branch_event_mutations_are_serialized` | narrative memory/concurrency | broad | yes: narrative/branch locking may be reachable | indirect | E attribution incomplete |
| `tests/test_recovered_routes.py::test_recovered_narrative_endpoints` | route/assertion | broad | yes: narrative route/service | indirect | E attribution incomplete |
| `tests/test_recovered_routes.py::test_narrative_confirmation_projection_snapshot_and_preview` | route/assertion | broad | yes: narrative route/service | indirect | E attribution incomplete |
| `tests/test_state_write_failure_vr.py::TestStateWriteFailureNotSilentlySwallowed::test_state_write_failure_reported_in_warnings` | narrative state/assertion | broad | yes: narrative state path | indirect | E attribution incomplete |

No row is classified D. The five E rows are retained because they can reach
dirty narrative/branch/route paths. The inspected 0D4-D stack did not enter
`cross_chapter_scope.py`, `cross_chapter_readiness_service.py`, or
`cross_chapter_turn_start_service.py`.
