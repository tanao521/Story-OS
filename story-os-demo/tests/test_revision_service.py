from __future__ import annotations

from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.job_manager import JobManager
from system.revision_service import RevisionService, RevisionStaleError


def make_service(tmp_path: Path, text: str = "# Chapter 1\n\nOriginal canon event.") -> RevisionService:
    context = get_project_context(tmp_path)
    path = context.chapters_dir / "chapter_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return RevisionService(context)


def test_revision_candidates_are_append_only_and_apply_creates_new_canon(tmp_path: Path):
    service = make_service(tmp_path)
    original = service.active_canon(1)
    revision = service.create_revision(1, reason="Fix the event")
    first = service.get_candidate(revision["revision_id"], revision["active_candidate_version_id"])
    candidate = service.save_candidate(revision["revision_id"], "# Chapter 1\n\nRevised canon event.")
    assert first["content"] == "# Chapter 1\n\nOriginal canon event."
    assert candidate["candidate_version_id"] != first["candidate_version_id"]
    service.review(revision["revision_id"], "approve", candidate_id=candidate["candidate_version_id"])
    result = service.apply(revision["revision_id"])
    assert result["canon_version"]["version_number"] == 2
    assert service.active_canon(1)["content"].endswith("Revised canon event.")
    versions = service.list_canon_versions(1)
    assert len(versions) == 2 and versions[0]["canon_version_id"] == original["canon_version_id"]
    assert not versions[0]["active"] and versions[1]["active"]
    state = service.store.read_json("data/derived_state.json", default={})
    assert any(item["artifact_type"] == "vector_memory" and item["status"] == "stale" for item in state["artifacts"])


def test_stale_revision_never_overwrites_current_canon(tmp_path: Path):
    service = make_service(tmp_path)
    revision = service.create_revision(1)
    candidate = service.save_candidate(revision["revision_id"], "Candidate replacement")
    service.review(revision["revision_id"], "approve", candidate_id=candidate["candidate_version_id"])
    service.store.write_markdown("data/chapters/chapter_001.md", "An external canon change")
    with pytest.raises(RevisionStaleError):
        service.apply(revision["revision_id"])
    assert service.store.read_markdown("data/chapters/chapter_001.md") == "An external canon change"
    assert service.get_revision(revision["revision_id"])["status"] == "stale"


def test_restore_creates_an_append_only_new_version(tmp_path: Path):
    service = make_service(tmp_path)
    revision = service.create_revision(1)
    candidate = service.save_candidate(revision["revision_id"], "Second canon")
    service.review(revision["revision_id"], "approve", candidate_id=candidate["candidate_version_id"])
    service.apply(revision["revision_id"])
    legacy = service.list_canon_versions(1)[0]["canon_version_id"]
    restored = service.restore_canon(1, legacy)
    assert restored["canon_version"]["version_number"] == 3
    assert service.active_canon(1)["content"].endswith("Original canon event.")



def test_apply_revision_job_uses_the_captured_project_context(tmp_path: Path):
    service = make_service(tmp_path)
    revision = service.create_revision(1)
    candidate = service.save_candidate(revision["revision_id"], "Job-owned canon")
    service.review(revision["revision_id"], "approve", candidate_id=candidate["candidate_version_id"])
    manager = JobManager(max_workers=1)
    manager.startup()
    job = manager.create_job("apply_revision", {"revision_id": revision["revision_id"], "chapter_id": 1}, context=service.context)
    import time
    for _ in range(300):
        record = manager.get_job(job["job_id"], context=service.context)
        if record["status"] in {"completed", "failed"}:
            break
        time.sleep(.02)
    manager.shutdown()
    assert record["status"] == "completed"
    assert service.active_canon(1)["content"] == "Job-owned canon"
