from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy, CommitStatus, SourceType, CommitResult
from system.revision_service import RevisionService


import tempfile
import shutil

@pytest.fixture
def temp_project():
    import os
    test_dir = os.path.join(os.path.dirname(__file__), "temp_test_projects")
    os.makedirs(test_dir, exist_ok=True)
    tmp_path = Path(tempfile.mkdtemp(dir=test_dir))
    
    project_root = tmp_path / "test_project"
    project_root.mkdir()
    
    data_dir = project_root / "data"
    data_dir.mkdir()
    
    (data_dir / "chapters").mkdir()
    (data_dir / "summaries").mkdir()
    (data_dir / "memory").mkdir()
    (data_dir / "canon_versions").mkdir()
    (data_dir / "versions").mkdir()
    (data_dir / "drafts").mkdir()
    (data_dir / "edited").mkdir()
    (data_dir / "manual").mkdir()
    
    (project_root / ".story_os").mkdir()
    (project_root / ".story_os" / "config.json").write_text(json.dumps({
        "project_id": "test_project",
        "project_name": "Test Project",
        "project_slug": "test-project",
    }), encoding="utf-8")
    
    state = {
        "current_chapter": 0,
        "current_stage": "chapter_draft_created",
        "plot": {"completed_events": []},
        "foreshadows": [],
        "timeline": [],
        "characters": {},
    }
    (data_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    
    story_spec = {"title": "Test Novel", "genre": "test"}
    (data_dir / "story_spec.json").write_text(json.dumps(story_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    
    yield get_project_context(project_root)
    
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def draft_file(temp_project):
    draft = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "draft_text": "这是第一章的测试内容。",
        "source_path": "data/drafts/chapter_001_draft_v001.json",
        "version": 1,
    }
    draft_path = temp_project.root / "data" / "drafts" / "chapter_001_draft_v001.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft_path


@pytest.fixture
def plan_file(temp_project):
    plan = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "chapter_goal": "测试目标",
        "conflict_design": {"main_conflict": "测试冲突"},
        "climax_design": {"climax_event": "测试高潮"},
        "phase_position": {"phase_title": "测试阶段"},
        "required_context": {"characters_to_use": [], "world_rules_to_use": []},
    }
    plan_path = temp_project.root / "data" / "next_chapter_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path


def test_unified_commit_service_exists():
    assert ChapterCommitService is not None


def test_commit_success(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result.status == CommitStatus.COMMITTED
    assert result.chapter_id == 1
    assert result.commit_id
    assert result.canon_revision_id
    assert result.source_type == SourceType.DRAFT
    
    chapter_path = temp_project.root / "data" / "chapters" / "chapter_001.md"
    assert chapter_path.exists()
    
    summary_path = temp_project.root / "data" / "summaries" / "chapter_001_summary.json"
    assert summary_path.exists()
    
    state = json.loads((temp_project.root / "data" / "state.json").read_text(encoding="utf-8"))
    assert state["current_chapter"] == 1
    assert state["current_stage"] == "chapter_committed"
    
    memory_index = json.loads((temp_project.root / "data" / "memory" / "memory_index.json").read_text(encoding="utf-8"))
    assert memory_index["chapters"]
    assert memory_index["chapters"][0]["chapter_id"] == 1
    
    revision_service = RevisionService(temp_project)
    active_canon = revision_service.active_canon(1)
    assert active_canon["canon_version_id"] == result.canon_revision_id


def test_duplicate_commit_idempotent(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    
    result1 = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    assert result1.status == CommitStatus.COMMITTED
    
    result2 = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    assert result2.status == CommitStatus.ALREADY_COMMITTED
    assert result2.commit_id == result1.commit_id
    
    revision_service = RevisionService(temp_project)
    versions = revision_service.list_canon_versions(1)
    assert len(versions) == 1


def test_new_content_creates_new_revision(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    
    result1 = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    assert result1.status == CommitStatus.COMMITTED
    
    new_draft = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "draft_text": "这是修改后的第一章内容。",
        "source_path": "data/drafts/chapter_001_draft_v002.json",
        "version": 2,
    }
    new_draft_path = temp_project.root / "data" / "drafts" / "chapter_001_draft_v002.json"
    new_draft_path.write_text(json.dumps(new_draft, ensure_ascii=False, indent=2), encoding="utf-8")
    
    result2 = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    assert result2.status == CommitStatus.COMMITTED
    assert result2.canon_revision_id != result1.canon_revision_id
    
    revision_service = RevisionService(temp_project)
    versions = revision_service.list_canon_versions(1)
    assert len(versions) == 2
    assert versions[-1]["active"] is True
    assert versions[0]["active"] is False


def test_source_priority_selected_over_draft(temp_project, draft_file, plan_file):
    selected = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "content": "这是selected版本内容。",
    }
    selected_path = temp_project.root / "data" / "versions" / "chapter_001_selected.json"
    selected_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result.source_type == SourceType.SELECTED
    
    chapter_content = (temp_project.root / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    assert "selected版本内容" in chapter_content


def test_source_priority_manual_over_edited(temp_project, plan_file):
    edited = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "edited_text": "这是edited版本内容。",
    }
    edited_path = temp_project.root / "data" / "edited" / "chapter_001_edited_v001.json"
    edited_path.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    
    manual = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "manual_text": "这是manual版本内容。",
    }
    manual_path = temp_project.root / "data" / "manual" / "chapter_001_manual_v001.json"
    manual_path.write_text(json.dumps(manual, ensure_ascii=False, indent=2), encoding="utf-8")
    
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result.source_type == SourceType.MANUAL
    
    chapter_content = (temp_project.root / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    assert "manual版本内容" in chapter_content


def test_source_priority_edited_over_draft(temp_project, draft_file, plan_file):
    edited = {
        "chapter_id": 1,
        "chapter_title": "第一章 测试",
        "edited_text": "这是edited版本内容。",
    }
    edited_path = temp_project.root / "data" / "edited" / "chapter_001_edited_v001.json"
    edited_path.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding="utf-8")
    
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result.source_type == SourceType.EDITED
    
    chapter_content = (temp_project.root / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    assert "edited版本内容" in chapter_content


def test_no_source_fails(temp_project, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result.status == CommitStatus.FAILED


def test_chapter_projection_matches_canon_revision(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    chapter_path = temp_project.root / "data" / "chapters" / "chapter_001.md"
    chapter_content = chapter_path.read_text(encoding="utf-8")
    
    revision_service = RevisionService(temp_project)
    active_canon = revision_service.active_canon(1)
    canon_content = active_canon["content"]
    
    assert chapter_content == canon_content


def test_legacy_chapter_adoption(temp_project, plan_file):
    legacy_chapter = "# 第一章 遗留章节\n\n这是遗留章节内容。\n"
    legacy_path = temp_project.root / "data" / "chapters" / "chapter_001.md"
    legacy_path.write_text(legacy_chapter, encoding="utf-8")
    
    revision_service = RevisionService(temp_project)
    revision_service.initialize_chapter_canon(1, legacy_chapter)
    active_canon = revision_service.active_canon(1)
    
    assert active_canon["canon_version_id"].startswith("legacy")
    assert active_canon["content"] == legacy_chapter


def test_post_commit_policy_full_includes_all_actions(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.FULL)
    
    assert result.status in (CommitStatus.COMMITTED, CommitStatus.COMMITTED_WITH_WARNINGS)
    assert "context_refresh" in result.post_commit
    assert "version_archive" in result.post_commit
    assert "obsidian_sync" in result.post_commit
    assert "chroma_index" in result.post_commit


def test_post_commit_policy_local_only_excludes_external_sync(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)

    assert result.status == CommitStatus.COMMITTED
    assert "context_refresh" in result.post_commit
    # chroma_index is a required local side-effect and must run under LOCAL_ONLY.
    assert "chroma_index" in result.post_commit
    # External-only side-effects remain excluded under LOCAL_ONLY.
    assert "version_archive" not in result.post_commit
    assert "obsidian_sync" not in result.post_commit


def test_post_commit_policy_deferred_no_actions(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.DEFERRED)
    
    assert result.status == CommitStatus.COMMITTED
    assert result.post_commit.get("context_refresh") == "deferred"


def test_post_commit_warnings_on_external_failure(temp_project, draft_file, plan_file):
    service = ChapterCommitService(temp_project)
    result = service.commit_chapter(1, post_commit_policy=PostCommitPolicy.FULL)
    
    if any(v != "success" for v in result.post_commit.values()):
        assert result.status == CommitStatus.COMMITTED_WITH_WARNINGS
        assert result.warnings


def test_two_projects_isolated(temp_project, draft_file, plan_file):
    project_a = temp_project
    
    import tempfile
    temp_dir = tempfile.mkdtemp(dir=Path("tests/temp_test_projects"))
    project_b_root = Path(temp_dir) / "test_project_b"
    project_b_root.mkdir()
    (project_b_root / "data").mkdir()
    (project_b_root / "data" / "chapters").mkdir()
    (project_b_root / "data" / "summaries").mkdir()
    (project_b_root / "data" / "memory").mkdir()
    (project_b_root / "data" / "canon_versions").mkdir()
    (project_b_root / "data" / "drafts").mkdir()
    (project_b_root / ".story_os").mkdir()
    (project_b_root / ".story_os" / "config.json").write_text(json.dumps({
        "project_id": "test_project_b",
        "project_name": "Test Project B",
        "project_slug": "test-project-b",
    }), encoding="utf-8")
    
    state_b = {"current_chapter": 0, "current_stage": "chapter_draft_created", "plot": {"completed_events": []}}
    (project_b_root / "data" / "state.json").write_text(json.dumps(state_b, ensure_ascii=False, indent=2), encoding="utf-8")
    
    draft_b = {
        "chapter_id": 1,
        "chapter_title": "第一章 项目B",
        "draft_text": "这是项目B的第一章内容。",
        "source_path": "data/drafts/chapter_001_draft_v001.json",
    }
    (project_b_root / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(
        json.dumps(draft_b, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    
    plan_b = {"chapter_id": 1, "chapter_title": "第一章 项目B", "chapter_goal": "项目B目标"}
    (project_b_root / "data" / "next_chapter_plan.json").write_text(
        json.dumps(plan_b, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    
    project_b = get_project_context(project_b_root)
    
    service_a = ChapterCommitService(project_a)
    service_b = ChapterCommitService(project_b)
    
    result_a = service_a.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    result_b = service_b.commit_chapter(1, post_commit_policy=PostCommitPolicy.LOCAL_ONLY)
    
    assert result_a.chapter_id == 1
    assert result_b.chapter_id == 1
    
    chapter_a = (project_a.root / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    chapter_b = (project_b.root / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    
    assert "测试内容" in chapter_a
    assert "项目B" in chapter_b
    
    assert not (project_a.root / "data" / "chapters" / "chapter_001.md").samefile(
        project_b.root / "data" / "chapters" / "chapter_001.md"
    )
    
    shutil.rmtree(project_b_root, ignore_errors=True)


def test_commit_result_structure():
    result = CommitResult(
        status=CommitStatus.COMMITTED,
        project_id="test",
        chapter_id=1,
        commit_id="abc123",
        source_type=SourceType.DRAFT,
        source_version_id="v1",
        source_hash="hash123",
        canon_revision_id="canon-001",
        chapter_path="data/chapters/chapter_001.md",
        summary_path="data/summaries/chapter_001_summary.json",
        core_commit={"canon_revision": "success", "chapter_projection": "success"},
        post_commit={"context_refresh": "success"},
        warnings=[],
    )
    
    assert result.status == CommitStatus.COMMITTED
    assert result.project_id == "test"
    assert result.chapter_id == 1
    assert result.commit_id == "abc123"
    assert result.source_type == SourceType.DRAFT
    assert result.source_version_id == "v1"
    assert result.source_hash == "hash123"
    assert result.canon_revision_id == "canon-001"
    assert result.chapter_path == "data/chapters/chapter_001.md"
    assert result.summary_path == "data/summaries/chapter_001_summary.json"
    assert "canon_revision" in result.core_commit
    assert "context_refresh" in result.post_commit
    assert result.warnings == []
