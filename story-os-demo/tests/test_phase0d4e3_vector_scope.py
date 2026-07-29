from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.vector_index_schema import VectorScope, SourceType, generate_scoped_document_id
import system.vector_index_lifecycle as lifecycle


class FakeCollection:
    def __init__(self): self.rows = {}; self.last_where = None
    def add(self, ids, documents, metadatas):
        for i, ident in enumerate(ids): self.rows[ident] = (documents[i], metadatas[i])
    def delete(self, where):
        flat = {next(iter(x)): next(iter(x.values())) for x in where.get("$and", [])} if "$and" in where else where
        self.rows = {k:v for k,v in self.rows.items() if not all(v[1].get(a)==b for a,b in flat.items())}
    def query(self, query_texts, n_results, where, include):
        self.last_where = where
        flat = {next(iter(x)): next(iter(x.values())) for x in where["$and"]}
        rows=[(k,v) for k,v in self.rows.items() if all(v[1].get(a)==b for a,b in flat.items())][:n_results]
        return {"ids":[[k for k,_ in rows]],"documents":[[v[0] for _,v in rows]],"metadatas":[[v[1] for _,v in rows]],"distances":[[0.0 for _ in rows]]}
    def count(self): return len(self.rows)


def _setup(tmp_path: Path):
    context=get_project_context(tmp_path); branches=BranchLifecycleService(context); common={"project_id":context.root.name,"timeline_id":"main"}
    branches.create("a",{**common,"branch_id":"a"}); branches.create("b",{**common,"branch_id":"b"})
    rev=branches.list_branches(**common)["registry_revision"]; branches.select("sel",{**common,"branch_id":"a","expected_registry_revision":rev})
    return context, branches


def test_scoped_ids_and_server_side_filter_isolate_branches(tmp_path, monkeypatch):
    context,_=_setup(tmp_path); col=FakeCollection(); monkeypatch.setattr(lifecycle,"_collection",lambda _context:col)
    a=VectorScope(context.root.name,"main","a","canon-1"); b=VectorScope(context.root.name,"main","b","canon-1")
    lifecycle.index_scoped_records(context,a,[{"text":"A_VECTOR_SENTINEL","source_type":"chapter","chapter_id":1}],operation_id="idx-a")
    lifecycle.index_scoped_records(context,b,[{"text":"B_VECTOR_SENTINEL","source_type":"chapter","chapter_id":1}],operation_id="idx-b")
    result=lifecycle.search_scoped(context,a,"sentinel")
    assert len(result)==1 and result[0]["text"]=="A_VECTOR_SENTINEL"
    assert {next(iter(item)) for item in col.last_where["$and"]} >= {"project_id","timeline_id","branch_id","canon_revision_id","canon_status","branch_lifecycle_status"}
    assert generate_scoped_document_id(a,SourceType.CHAPTER,"1",0,"f"*64) != generate_scoped_document_id(b,SourceType.CHAPTER,"1",0,"f"*64)


def test_inactive_and_archived_business_queries_fail_closed(tmp_path, monkeypatch):
    context,branches=_setup(tmp_path); col=FakeCollection(); monkeypatch.setattr(lifecycle,"_collection",lambda _context:col)
    b=VectorScope(context.root.name,"main","b","canon-1")
    lifecycle.index_scoped_records(context,b,[{"text":"B","source_type":"chapter","chapter_id":1}],operation_id="idx")
    with pytest.raises(lifecycle.VectorScopeRequired): lifecycle.search_scoped(context,b,"B",business=True)
    common={"project_id":context.root.name,"timeline_id":"main"}; rev=branches.list_branches(**common)["registry_revision"]
    branches.archive("arc",{**common,"branch_id":"b","expected_registry_revision":rev})
    with pytest.raises(lifecycle.VectorScopeRequired): lifecycle.search_scoped(context,b,"B",business=False)


def test_vector_sync_authority_replays_and_scope_collision_fails(tmp_path, monkeypatch):
    context,_=_setup(tmp_path); col=FakeCollection(); monkeypatch.setattr(lifecycle,"_collection",lambda _context:col)
    scope=VectorScope(context.root.name,"main","a","canon-1")
    first=lifecycle.sync_branch_index(context,scope,operation_id="sync-a",operation_type="rebuild")
    assert first["vector_ready"] is True
    assert lifecycle.sync_branch_index(context,scope,operation_id="sync-a",operation_type="rebuild")["idempotent_replay"] is True
    other=VectorScope(context.root.name,"main","a","canon-2")
    with pytest.raises(lifecycle.VectorIndexLifecycleError): lifecycle.sync_branch_index(context,other,operation_id="sync-a",operation_type="rebuild")
