from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.vector_client_manager import VectorClientManager
from system.vector_index_lifecycle import sync_branch_index
from system.vector_index_schema import VectorScope, branch_manifest_path


class LocalCollection:
    def __init__(self, metadata=None):
        self.rows = {}
        self.metadata = metadata

    def add(self, ids, documents, metadatas):
        for index, item in enumerate(ids):
            self.rows[item] = (documents[index], metadatas[index])

    def delete(self, where):
        return None

    def count(self):
        return len(self.rows)


class LocalClient:
    def __init__(self):
        self.collections = {}
        self.closed = False

    def get_collection(self, name, **_kwargs):
        return self.collections[name]

    def create_collection(self, name, metadata=None, **_kwargs):
        collection = LocalCollection(metadata=metadata)
        self.collections[name] = collection
        return collection

    def close(self):
        self.closed = True


def _context(tmp_path: Path):
    context = get_project_context(tmp_path)
    context.chapters_dir.mkdir(parents=True)
    (context.chapters_dir / "chapter_001.md").write_text("# One\n\nRC7 local authority.", encoding="utf-8")
    branches = BranchLifecycleService(context)
    values = {"project_id": context.root.name, "timeline_id": "main", "branch_id": "main"}
    branches.create("rc7-create", values)
    revision = branches.list_branches(project_id=context.root.name, timeline_id="main")["registry_revision"]
    branches.select("rc7-select", {**values, "expected_registry_revision": revision})
    return context


def test_explicit_manager_is_instance_scoped_and_default_path_is_unchanged(tmp_path):
    context = _context(tmp_path)
    client = LocalClient()
    name = f"rc7_{uuid4().hex}"
    injected = VectorClientManager(client_factory=lambda _: client, collection_name=name)
    default = VectorClientManager()
    assert injected is not default
    assert injected.get_client(context) is client
    assert default._client_factory is None
    injected.close_client(context)
    assert client.closed is True


def test_sync_branch_index_uses_explicit_manager_and_publishes_valid_manifest(tmp_path):
    context = _context(tmp_path)
    client = LocalClient()
    manager = VectorClientManager(client_factory=lambda _: client, collection_name=f"rc7_{uuid4().hex}")
    # RC10 made the repository n-gram embedding contract mandatory even for
    # injected clients. This local fixture ignores embeddings, but must still
    # provide an explicit injected embedding seam instead of relying on the
    # optional chromadb package being installed in this test environment.
    manager._chromadb_module = object()
    manager._embedding_fn = lambda values: values
    scope = VectorScope(context.root.name, "main", "main", "canon-rc7")
    result = sync_branch_index(
        context, scope, operation_id="rc7-sync", operation_type="rebuild",
        vector_client_manager=manager,
    )
    assert result["vector_ready"] is True
    assert branch_manifest_path(context.data_dir, scope).exists()
    assert manager.get_collection(context).count() == 1
    manager.close_client(context)
