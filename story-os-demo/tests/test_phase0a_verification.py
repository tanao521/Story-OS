import json
import shutil
import tempfile
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy, CommitStatus, SourceType
from system.commit_run_store import CommitRunStore
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
    (project_root / "data" / "manual").mkdir()
    (project_root / ".story_os").mkdir()

    (project_root / ".story_os" / "config.json").write_text(json.dumps({
        "project_id": "test_project",
        "project_name": "Test Project",
        "project_slug": "test-project",
    }), encoding="utf-8")

    state = {"current_chapter": 0, "current_stage": "chapter_draft_created", "plot": {"completed_events": []}}
    (project_root / "data" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    plan = {"chapter_id": 1, "chapter_title": "第一章 测试", "chapter_goal": "测试目标"}
    (project_root / "data" / "next_chapter_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    context = get_project_context(project_root)
    yield context

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_same_content_different_version_id_dedup(temp_project):
    manual_v1 = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "manual_text": "这是完全相同的正文内容。",
    }
    manual_v2 = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "manual_text": "这是完全相同的正文内容。",
    }

    (temp_project.root / "data" / "manual" / "chapter_001_manual_v001.json").write_text(
        json.dumps(manual_v1, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (temp_project.root / "data" / "manual" / "chapter_001_manual_v002.json").write_text(
        json.dumps(manual_v2, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    revision_service = RevisionService(temp_project)

    service = ChapterCommitService(temp_project)
    result1 = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result1.status == CommitStatus.COMMITTED
    assert result1.canon_revision_id is not None

    versions_after_first = revision_service.list_canon_versions(1)
    version_count_after_first = len(versions_after_first)

    (temp_project.root / "data" / "manual" / "chapter_001_manual_v001.json").unlink()

    service2 = ChapterCommitService(temp_project)
    result2 = service2.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    versions_after_second = revision_service.list_canon_versions(1)
    version_count_after_second = len(versions_after_second)

    assert version_count_after_second == version_count_after_first, \
        f"Expected same version count ({version_count_after_first}), but got {version_count_after_second}. " \
        f"This indicates duplicate revision creation for identical content."


def test_cross_process_idempotency(temp_project):
    draft = {
        "chapter_id": 1,
        "chapter_title": "第一章 跨进程测试",
        "draft_text": "跨进程幂等性测试内容。",
    }
    (temp_project.root / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    revision_service = RevisionService(temp_project)

    service1 = ChapterCommitService(temp_project)
    result1 = service1.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result1.status == CommitStatus.COMMITTED
    assert result1.canon_revision_id is not None

    versions_after_first = revision_service.list_canon_versions(1)
    version_count_after_first = len(versions_after_first)

    del service1

    service2 = ChapterCommitService(temp_project)
    result2 = service2.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result2.status == CommitStatus.ALREADY_COMMITTED

    versions_after_second = revision_service.list_canon_versions(1)
    version_count_after_second = len(versions_after_second)

    assert version_count_after_second == version_count_after_first

    state = revision_service.store.read_json("data/state.json", default={})
    completed_events = state.get("plot", {}).get("completed_events", [])
    assert len([e for e in completed_events if "第1章已提交" in e]) == 1


def test_post_commit_compensation(temp_project):
    draft = {
        "chapter_id": 1,
        "chapter_title": "第一章 补偿测试",
        "draft_text": "后置任务补偿测试内容。",
    }
    (temp_project.root / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    service1 = ChapterCommitService(temp_project)

    def failing_sync(*args):
        return "warning: Simulated Obsidian sync failure"

    service1._sync_obsidian = failing_sync

    result1 = service1.commit_chapter(1, post_commit_policy=PostCommitPolicy.FULL)

    assert result1.status == CommitStatus.COMMITTED_WITH_WARNINGS
    assert "Obsidian" in str(result1.warnings)

    del service1

    # Verify persistent run record exists
    run_store = CommitRunStore(temp_project)
    run = run_store.load(result1.commit_id)
    assert run is not None
    assert run.post_commit["obsidian_sync"].status == "failed"

    service2 = ChapterCommitService(temp_project)

    def success_sync(*args):
        return "success"

    service2._sync_obsidian = success_sync
    service2._index_chroma = lambda *args: "success"
    service2._create_reflection_job = lambda *args: "success"
    service2._update_planning_anchor = lambda *args: "success"

    result2 = service2.commit_chapter(1, post_commit_policy=PostCommitPolicy.FULL)

    assert result2.status in [CommitStatus.COMMITTED, CommitStatus.COMMITTED_WITH_WARNINGS]
    assert result2.post_commit.get("obsidian_sync") == "success"