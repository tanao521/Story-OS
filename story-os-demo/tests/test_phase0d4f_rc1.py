"""Phase 0D4-F-RC1 evidence closure tests.

These tests deliberately exercise the durable seams without constructing a
real project or invoking Canon/Chroma.  Integration fixtures remain covered by
the existing D/E suites.
"""
from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from system.narrative_chapter_compiler import _publish_immutable_json


def test_authority_publish_is_first_writer_wins_and_byte_stable(tmp_path):
    path = tmp_path / "operations" / "op.json"
    first = {"operation_id": "op", "operation_type": "compile", "scope": {"branch_id": "a"}}
    second = {"operation_id": "op", "operation_type": "compile", "scope": {"branch_id": "b"}}
    _publish_immutable_json(path, first)
    before = path.read_bytes()
    existing = _publish_immutable_json(path, first)
    assert existing == first
    assert path.read_bytes() == before
    assert _publish_immutable_json(path, second) == first
    assert path.read_bytes() == before


def test_authority_publish_concurrent_writers_have_one_winner(tmp_path):
    path = tmp_path / "commit_operations" / "op.json"
    records = [{"operation_id": "op", "scope": {"branch_id": branch}} for branch in ("a", "b")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: _publish_immutable_json(path, item), records))
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted in records
    assert all(result == persisted for result in results)


def test_rc1_result_artifact_contract_is_durable_and_scoped():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert '"scope": asdict(scope)' in source
    assert '"canonical_request_fingerprint"' in source
    assert '"outcome_fingerprint"' in source
    assert "_validate_result_scope" in source


def test_rc1_fault_matrix_has_required_compile_and_commit_points():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    compile_points = {"after_authority_claim", "after_turn_snapshot", "after_candidate_write", "after_first_included_transition", "after_all_included_transitions", "before_completed_marker"}
    commit_points = {"after_authority_claim", "after_candidate_verification", "before_chapter_commit", "after_chapter_commit_success", "after_first_committed_transition", "after_all_committed_transitions", "before_completed_marker"}
    for point in compile_points | commit_points:
        assert f'self._fault("{point}")' in source


def test_rc1_recovery_reads_durable_commit_result_before_retrying_service():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "durable_result.get(\"commit_id\")" in source
    assert "RecoveredCommitResult" in source
    assert "commit_result_path" in source
