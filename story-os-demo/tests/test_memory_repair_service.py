from __future__ import annotations

from pathlib import Path

from core.project_context import get_project_context
from system.memory_repair_service import MemoryRepairService


def _chapter(context, chapter_id: int = 1) -> None:
    context.chapters_dir.mkdir(parents=True, exist_ok=True)
    (context.chapters_dir / f"chapter_{chapter_id:03d}.md").write_text(
        "\u7b2c\u4e00\u7ae0\n\u591c\u96e8\u538b\u5728\u957f\u8857\uff0c\u6c5f\u5b81\u63e1\u7d27\u4e86\u4fe1\u7b3a\u3002\n\u4ed6\u51b3\u5b9a\u5929\u4eae\u524d\u627e\u5230\u5931\u8e2a\u7684\u59d0\u59d0\u3002",
        encoding="utf-8",
    )


def test_quality_report_is_bound_to_active_canon(tmp_path: Path) -> None:
    context = get_project_context(tmp_path)
    _chapter(context)
    service = MemoryRepairService(context)

    assert service.quality_status()["status"] == "missing"
    result = service.build_quality_report(1)
    item = service.quality_status()["items"][0]

    assert result["status"] == "completed"
    assert item["status"] == "available"
    assert item["report"]["project_id"] == context.root.name
    assert item["report"]["canon_version_id"] == item["canon_version_id"]
    assert item["report"]["analysis_profile"] == "lite"


def test_vector_repair_records_empty_and_ready_states(tmp_path: Path, monkeypatch) -> None:
    context = get_project_context(tmp_path)
    service = MemoryRepairService(context)
    monkeypatch.setattr(
        "system.vector_memory.build_or_update_index",
        lambda data_dir: {"status": "success", "outputs": {"chunks_indexed": 1}, "warnings": []},
    )

    assert service.initialize_vector_index()["status"] == "empty"
    assert service.vector_status()["status"] == "empty"

    _chapter(context)
    assert service.initialize_vector_index(rebuild=True)["status"] == "ready"
    metadata = service.vector_status()["metadata"]
    assert metadata["project_id"] == context.root.name
    assert metadata["embedding_provider"] == "local_ngram"
