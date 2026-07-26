import json
import shutil
import tempfile
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy, CommitStatus
from system.revision_service import RevisionService


@pytest.fixture
def temp_project():
    test_dir = Path("tests/temp_test_projects")
    test_dir.mkdir(exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=test_dir)
    project_root = Path(temp_dir) / "test_project"
    project_root.mkdir()

    (project_root / "data").mkdir()
    (project_root / "data" / "chapters").mkdir()
    (project_root / "data" / "summaries").mkdir()
    (project_root / "data" / "memory").mkdir()
    (project_root / "data" / "canon_versions").mkdir()
    (project_root / "data" / "drafts").mkdir()
    (project_root / ".story_os").mkdir()

    (project_root / ".story_os" / "config.json").write_text(json.dumps({
        "project_id": "test_project",
        "project_name": "Test Project",
        "project_slug": "test-project",
    }), encoding="utf-8")

    state = {"current_chapter": 0, "current_stage": "chapter_draft_created", "plot": {"completed_events": []}}
    (project_root / "data" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    draft = {
        "chapter_id": 1,
        "chapter_title": "第一章 回滚测试",
        "draft_text": "这是回滚测试的章节内容。",
        "source_path": "data/drafts/chapter_001_draft_v001.json",
    }
    (project_root / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    plan = {"chapter_id": 1, "chapter_title": "第一章 回滚测试", "chapter_goal": "测试目标"}
    (project_root / "data" / "next_chapter_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    context = get_project_context(project_root)
    yield context

    shutil.rmtree(temp_dir, ignore_errors=True)


def _capture_disk_state(project_root: Path, chapter_id: int) -> dict:
    """Capture pre-commit disk state for rollback verification."""
    state = {}
    chapter_path = project_root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"
    summary_path = project_root / "data" / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
    state_path = project_root / "data" / "state.json"
    memory_path = project_root / "data" / "memory" / "memory_index.json"
    canon_dir = project_root / "data" / "canon_versions" / f"chapter_{chapter_id:03d}"

    state["chapter_exists"] = chapter_path.exists()
    state["chapter_content"] = chapter_path.read_text(encoding="utf-8") if chapter_path.exists() else None
    state["summary_exists"] = summary_path.exists()
    state["summary_content"] = summary_path.read_text(encoding="utf-8") if summary_path.exists() else None
    state["state_content"] = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    state["memory_exists"] = memory_path.exists()
    state["memory_content"] = memory_path.read_text(encoding="utf-8") if memory_path.exists() else None
    state["canon_files"] = sorted([p.name for p in canon_dir.glob("*")]) if canon_dir.exists() else []
    state["canon_index_exists"] = (canon_dir / "canon_index.json").exists() if canon_dir.exists() else False

    return state


def _assert_rollback(project_root: Path, chapter_id: int, before: dict) -> None:
    """Verify disk state matches pre-commit snapshot."""
    chapter_path = project_root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"
    summary_path = project_root / "data" / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
    state_path = project_root / "data" / "state.json"
    memory_path = project_root / "data" / "memory" / "memory_index.json"
    canon_dir = project_root / "data" / "canon_versions" / f"chapter_{chapter_id:03d}"

    assert chapter_path.exists() == before["chapter_exists"]
    if before["chapter_content"] is not None:
        assert chapter_path.read_text(encoding="utf-8") == before["chapter_content"]

    assert summary_path.exists() == before["summary_exists"]
    if before["summary_content"] is not None:
        assert summary_path.read_text(encoding="utf-8") == before["summary_content"]

    assert state_path.read_text(encoding="utf-8") == before["state_content"]

    assert memory_path.exists() == before["memory_exists"]
    if before["memory_content"] is not None:
        assert memory_path.read_text(encoding="utf-8") == before["memory_content"]

    if canon_dir.exists():
        after_files = sorted([p.name for p in canon_dir.glob("*")])
        assert after_files == before["canon_files"], f"Canon files changed: {after_files} vs {before['canon_files']}"


def test_rollback_on_state_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    call_count = {"count": 0}
    original_write_json = service.data_store.write_json

    def failing_write_json(path, data):
        path_str = str(path)
        if "state.json" in path_str:
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise Exception("Simulated state write failure")
        return original_write_json(path, data)

    monkeypatch.setattr(service.data_store, "write_json", failing_write_json)
    monkeypatch.setattr(service.revision_service.store, "write_json", failing_write_json)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    assert "state write failure" in str(result.warnings) or "Core commit failed" in str(result.warnings)

    _assert_rollback(temp_project.root, 1, before)


def test_rollback_on_summary_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    original_write_json = service.data_store.write_json

    def failing_write_json(path, data):
        path_str = str(path)
        if "summary" in path_str and "_summary.json" in path_str:
            raise Exception("Simulated summary write failure")
        return original_write_json(path, data)

    monkeypatch.setattr(service.data_store, "write_json", failing_write_json)
    monkeypatch.setattr(service.revision_service.store, "write_json", failing_write_json)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    _assert_rollback(temp_project.root, 1, before)


def test_rollback_on_memory_index_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    original_write_json = service.data_store.write_json

    def failing_write_json(path, data):
        path_str = str(path)
        if "memory_index.json" in path_str:
            raise Exception("Simulated memory write failure")
        return original_write_json(path, data)

    monkeypatch.setattr(service.data_store, "write_json", failing_write_json)
    monkeypatch.setattr(service.revision_service.store, "write_json", failing_write_json)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    _assert_rollback(temp_project.root, 1, before)


def test_rollback_on_chapter_projection_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    original_write_markdown = service.data_store.write_markdown

    def failing_write_markdown(path, content):
        path_str = str(path)
        if "chapters/chapter_001.md" in path_str:
            raise Exception("Simulated chapter projection write failure")
        return original_write_markdown(path, content)

    monkeypatch.setattr(service.data_store, "write_markdown", failing_write_markdown)
    monkeypatch.setattr(service.revision_service.store, "write_markdown", failing_write_markdown)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    _assert_rollback(temp_project.root, 1, before)


def test_rollback_on_canon_revision_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    original_write_markdown = service.data_store.write_markdown

    def failing_write_markdown(path, content):
        path_str = str(path)
        if "canon_versions" in path_str and "canon-chapter" in path_str:
            raise Exception("Simulated canon revision write failure")
        return original_write_markdown(path, content)

    monkeypatch.setattr(service.data_store, "write_markdown", failing_write_markdown)
    monkeypatch.setattr(service.revision_service.store, "write_markdown", failing_write_markdown)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    _assert_rollback(temp_project.root, 1, before)


def test_rollback_on_canon_index_write_failure(temp_project, monkeypatch):
    before = _capture_disk_state(temp_project.root, 1)

    service = ChapterCommitService(temp_project)
    original_write_json = service.data_store.write_json

    def failing_write_json(path, data):
        path_str = str(path)
        if "canon_index.json" in path_str:
            raise Exception("Simulated canon index write failure")
        return original_write_json(path, data)

    monkeypatch.setattr(service.data_store, "write_json", failing_write_json)
    monkeypatch.setattr(service.revision_service.store, "write_json", failing_write_json)

    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.FAILED
    _assert_rollback(temp_project.root, 1, before)
