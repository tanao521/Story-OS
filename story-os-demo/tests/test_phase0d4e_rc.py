"""Phase 0D4-E-RC integrated acceptance for branch-scoped vector authority."""
from __future__ import annotations

import json
import shutil
import sys
import gc
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.project_context import bind_project_context, get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.branch_narrative_memory_service import BranchMemoryInactive, BranchMemoryService
from system.vector_client_manager import VectorClientManager
from system.vector_index_schema import VectorScope
import system.vector_index_lifecycle as lifecycle


class FakeCollection:
    """Captures the real Chroma query shape while enforcing its where clause."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict]] = {}
        self.last_where: dict | None = None
        self.force_mismatched_result = False

    def add(self, ids, documents, metadatas):
        for index, doc_id in enumerate(ids):
            self.rows[doc_id] = (documents[index], dict(metadatas[index]))

    def delete(self, where):
        terms = where.get("$and", [where])
        expected = {next(iter(term)): next(iter(term.values())) for term in terms}
        self.rows = {
            doc_id: row for doc_id, row in self.rows.items()
            if not all(row[1].get(key) == value for key, value in expected.items())
        }

    def query(self, query_texts, n_results, where, include):
        self.last_where = where
        expected = {next(iter(term)): next(iter(term.values())) for term in where["$and"]}
        rows = [row for row in self.rows.items() if all(row[1][1].get(key) == value for key, value in expected.items())]
        if self.force_mismatched_result and rows:
            doc_id, (text, meta) = rows[0]
            bad = dict(meta); bad["branch_id"] = "wrong_branch"
            rows = [(doc_id, (text, bad))]
        rows = rows[:n_results]
        return {
            "ids": [[doc_id for doc_id, _ in rows]],
            "documents": [[row[0] for _, row in rows]],
            "metadatas": [[row[1] for _, row in rows]],
            "distances": [[0.0 for _ in rows]],
        }

    def count(self):
        return len(self.rows)


def _setup(tmp_path: Path):
    context = get_project_context(tmp_path)
    context.chapters_dir.mkdir(parents=True, exist_ok=True)
    branches = BranchLifecycleService(context)
    common = {"project_id": context.root.name, "timeline_id": "main"}
    for branch_id in ("a", "b", "c"):
        branches.create(f"create-{branch_id}", {**common, "branch_id": branch_id})
    revision = branches.list_branches(**common)["registry_revision"]
    branches.select("select-a", {**common, "branch_id": "a", "expected_registry_revision": revision})
    revision = branches.list_branches(**common)["registry_revision"]
    branches.archive("archive-c", {**common, "branch_id": "c", "expected_registry_revision": revision})
    return context, branches, common


def _scope(context, branch_id: str, revision: str = "canon-1") -> VectorScope:
    return VectorScope(context.root.name, "main", branch_id, revision)


def test_server_side_where_and_application_verification_are_both_mandatory(tmp_path, monkeypatch):
    context, _branches, _common = _setup(tmp_path)
    collection = FakeCollection()
    monkeypatch.setattr(lifecycle, "_collection", lambda _: collection)
    a, b = _scope(context, "a"), _scope(context, "b")
    lifecycle.index_scoped_records(context, a, [{"text": "A_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="index-a")
    lifecycle.index_scoped_records(context, b, [{"text": "B_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="index-b")
    # A branchless legacy-looking row cannot consume A's top-k because Chroma
    # receives the complete scope before the application sees any result.
    collection.rows["legacy"] = ("A_VECTOR_SENTINEL", {"project_id": context.root.name, "timeline_id": "main"})
    assert [row["text"] for row in lifecycle.search_scoped(context, a, "sentinel", max_results=1)] == ["A_VECTOR_SENTINEL"]
    assert collection.last_where == {
        "$and": [
            {"project_id": context.root.name}, {"timeline_id": "main"}, {"branch_id": "a"},
            {"canon_revision_id": "canon-1"}, {"canon_status": "active"}, {"branch_lifecycle_status": "open"},
        ]
    }
    collection.force_mismatched_result = True
    assert lifecycle.search_scoped(context, a, "sentinel") == []


def test_branch_lifecycle_immediately_controls_vector_visibility_and_readiness(tmp_path, monkeypatch):
    context, branches, common = _setup(tmp_path)
    collection = FakeCollection()
    monkeypatch.setattr(lifecycle, "_collection", lambda _: collection)
    a, b = _scope(context, "a"), _scope(context, "b")
    lifecycle.index_scoped_records(context, a, [{"text": "A_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="index-a")
    lifecycle.index_scoped_records(context, b, [{"text": "B_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="index-b")
    assert [row["text"] for row in lifecycle.search_scoped(context, a, "A_VECTOR_SENTINEL")] == ["A_VECTOR_SENTINEL"]
    with pytest.raises(lifecycle.VectorScopeRequired):
        lifecycle.search_scoped(context, b, "B_VECTOR_SENTINEL")

    revision = branches.list_branches(**common)["registry_revision"]
    branches.select("select-b", {**common, "branch_id": "b", "expected_registry_revision": revision})
    with pytest.raises(lifecycle.VectorScopeRequired):
        lifecycle.search_scoped(context, a, "A_VECTOR_SENTINEL")
    assert [row["text"] for row in lifecycle.search_scoped(context, b, "B_VECTOR_SENTINEL")] == ["B_VECTOR_SENTINEL"]

    revision = branches.list_branches(**common)["registry_revision"]
    branches.archive("archive-b", {**common, "branch_id": "b", "replacement_branch_id": "a", "expected_registry_revision": revision})
    lifecycle.sync_branch_index(context, b, operation_id="vector-archive-b", operation_type="archive")
    with pytest.raises(lifecycle.VectorScopeRequired):
        lifecycle.search_scoped(context, b, "B_VECTOR_SENTINEL")
    assert [row["text"] for row in lifecycle.search_scoped(context, a, "A_VECTOR_SENTINEL")] == ["A_VECTOR_SENTINEL"]

    revision = branches.list_branches(**common)["registry_revision"]
    branches.restore("restore-b", {**common, "branch_id": "b", "expected_registry_revision": revision})
    revision = branches.list_branches(**common)["registry_revision"]
    branches.select("select-b-again", {**common, "branch_id": "b", "expected_registry_revision": revision})
    with pytest.raises(lifecycle.BranchVectorNotReady):
        lifecycle.search_scoped(context, b, "B_VECTOR_SENTINEL")
    lifecycle.sync_branch_index(context, b, operation_id="vector-rebuild-b", operation_type="rebuild")
    assert lifecycle.search_scoped(context, b, "B_VECTOR_SENTINEL") == []


def test_branch_memory_visibility_tracks_active_branch_without_rewriting_other_branch(tmp_path):
    context, branches, common = _setup(tmp_path)
    memory = BranchMemoryService(context)
    timeline = memory.scope(context.root.name, "main", "a")
    memory.append_event(timeline, "a", {"chapter_id": 1, "event_type": "sentinel", "payload": {"value": "A_MEMORY_SENTINEL"}})
    timeline_b = memory.scope(context.root.name, "main", "b")
    memory.append_event(timeline_b, "b", {"chapter_id": 1, "event_type": "sentinel", "payload": {"value": "B_MEMORY_SENTINEL"}})
    a_before = (context.data_dir / "narrative_memory" / "events" / "main" / "a" / "chapter_001.json").read_bytes()
    assert memory.events(timeline, "a")[0]["payload"]["value"] == "A_MEMORY_SENTINEL"
    with pytest.raises(BranchMemoryInactive):
        memory.events(timeline_b, "b")
    revision = branches.list_branches(**common)["registry_revision"]
    branches.select("memory-select-b", {**common, "branch_id": "b", "expected_registry_revision": revision})
    assert memory.events(timeline_b, "b")[0]["payload"]["value"] == "B_MEMORY_SENTINEL"
    assert (context.data_dir / "narrative_memory" / "events" / "main" / "a" / "chapter_001.json").read_bytes() == a_before


@pytest.mark.parametrize("fault_point", [
    "after_authority_claim", "after_source_scan", "after_old_scope_marked_stale",
    "after_first_record_batch", "after_all_records_indexed", "after_manifest_publication",
    "after_verification", "before_completed_marker",
])
def test_operation_recovery_replays_same_authority_without_cross_branch_mutation(tmp_path, monkeypatch, fault_point):
    context, _branches, _common = _setup(tmp_path)
    (context.chapters_dir / "chapter_001.md").write_text("A_VECTOR_SENTINEL", encoding="utf-8")
    collection = FakeCollection()
    monkeypatch.setattr(lifecycle, "_collection", lambda _: collection)
    scope = _scope(context, "a")

    def inject(point):
        if point == fault_point:
            raise RuntimeError(f"injected:{point}")

    monkeypatch.setattr(lifecycle, "_fault_injector", inject)
    with pytest.raises(RuntimeError, match=fault_point):
        lifecycle.sync_branch_index(context, scope, operation_id=f"recovery-{fault_point}", operation_type="rebuild")
    authority = context.data_dir / "chroma" / "operations" / f"recovery-{fault_point}.json"
    authority_bytes = authority.read_bytes()
    monkeypatch.setattr(lifecycle, "_fault_injector", None)
    result = lifecycle.sync_branch_index(context, scope, operation_id=f"recovery-{fault_point}", operation_type="rebuild")
    assert result["status"] == "success"
    assert authority.read_bytes() == authority_bytes
    assert collection.count() == 1
    phase = json.loads((context.data_dir / "chroma" / "operations" / f"recovery-{fault_point}.phase.json").read_text(encoding="utf-8"))
    assert phase["phase"] == "COMPLETED" and phase["branch_id"] == "a"
    assert lifecycle.sync_branch_index(context, scope, operation_id=f"recovery-{fault_point}", operation_type="rebuild")["idempotent_replay"] is True


def test_operation_phase_or_manifest_tampering_fails_closed(tmp_path, monkeypatch):
    context, _branches, _common = _setup(tmp_path)
    collection = FakeCollection()
    monkeypatch.setattr(lifecycle, "_collection", lambda _: collection)
    scope = _scope(context, "a")
    lifecycle.index_scoped_records(context, scope, [{"text": "A", "source_type": "chapter", "chapter_id": 1}], operation_id="initial")
    manifest_path = context.data_dir / "chroma" / "manifests" / "main" / "a.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")); manifest["branch_id"] = "b"; manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(lifecycle.BranchVectorNotReady):
        lifecycle.search_scoped(context, scope, "A")

    lifecycle.sync_branch_index(context, scope, operation_id="phase-tamper", operation_type="rebuild")
    phase_path = context.data_dir / "chroma" / "operations" / "phase-tamper.phase.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8")); phase["branch_id"] = "b"; phase_path.write_text(json.dumps(phase), encoding="utf-8")
    with pytest.raises(lifecycle.VectorOperationConflict):
        lifecycle.sync_branch_index(context, scope, operation_id="phase-tamper", operation_type="rebuild")


def test_initialize_http_forwards_complete_scope_and_is_safe(monkeypatch, tmp_path):
    from web.app import app
    import web.routes as routes

    captured = {}

    def command(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "message": "queued", "outputs": {"job": {"job_id": "job-1"}}}

    monkeypatch.setattr(routes.commands, "initialize_vector_index_command", command)
    context, _branches, _common = _setup(tmp_path)
    payload = {"project_id": context.root.name, "timeline_id": "main", "branch_id": "a", "canon_revision_id": "canon-1", "rebuild": True}
    with bind_project_context(context):
        client = TestClient(app)
        response = client.post("/api/vector-index/initialize", json=payload)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert captured == payload
    monkeypatch.undo()
    with bind_project_context(context):
        missing = TestClient(app).post("/api/vector-index/initialize", json={})
    assert missing.status_code == 200 and missing.headers["cache-control"] == "no-store"
    assert missing.json()["errors"] == ["VECTOR_SCOPE_REQUIRED"]


def test_legacy_vector_static_guard_has_only_explicit_compatibility_allowlist():
    root = Path(__file__).resolve().parents[1]
    scanned = [*sorted((root / "system").glob("*.py")), *sorted((root / "web").glob("*.py")), root / "commands.py"]
    text_by_path = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in scanned}
    production = {path: text for path, text in text_by_path.items() if path != "system/vector_memory.py"}
    forbidden = re.compile(r"(?:from\s+system\.vector_memory\s+import|import\s+system\.vector_memory|\bvector_memory\s*\.)")
    matches = [(path, match.group(0)) for path, text in production.items() for match in forbidden.finditer(text)]
    assert matches == []
    persistent = [path for path, text in text_by_path.items() if "PersistentClient(" in text]
    assert set(persistent) <= {"system/vector_client_manager.py", "system/vector_memory.py"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows client lifecycle acceptance")
def test_windows_real_chroma_client_can_close_and_release_temp_project(tmp_path):
    pytest.importorskip("chromadb")
    project_root = tmp_path / "windows_chroma_project"
    project_root.mkdir()
    context, _branches, _common = _setup(project_root)
    a, b = _scope(context, "a"), _scope(context, "b")
    lifecycle.index_scoped_records(context, a, [{"text": "A_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="win-a")
    lifecycle.index_scoped_records(context, b, [{"text": "B_VECTOR_SENTINEL", "source_type": "chapter", "chapter_id": 1}], operation_id="win-b")
    assert lifecycle.search_scoped(context, a, "A_VECTOR_SENTINEL")
    VectorClientManager().close_client(context)
    reopened = VectorClientManager().get_collection(context)
    assert reopened is not None
    VectorClientManager().close_client(context)
    # The caller deliberately releases its final collection reference before
    # deleting the temporary project, mirroring an abnormal/lost-reference
    # client exit after the manager has stopped the underlying system.
    del reopened
    gc.collect()
    shutil.rmtree(project_root)
    assert not project_root.exists()
