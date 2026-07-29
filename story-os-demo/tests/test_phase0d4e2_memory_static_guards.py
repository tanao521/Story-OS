from pathlib import Path


def test_branch_memory_code_has_no_vector_mutation_imports():
    root = Path(__file__).resolve().parents[1]
    content = "\n".join((root / name).read_text(encoding="utf-8") for name in ["system/branch_narrative_memory_service.py", "web/branch_narrative_memory_routes.py"])
    forbidden = ["PersistentClient", "collection.add", "collection.upsert", "collection.delete", "collection.query", "vector_memory", "vector_index_lifecycle"]
    assert not any(token in content for token in forbidden)
