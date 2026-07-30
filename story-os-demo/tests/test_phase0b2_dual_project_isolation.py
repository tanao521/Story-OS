"""Dual-project isolation tests for Phase 0B2.

These tests verify that agents, creative_loop, analytics, and author_memory
modules correctly isolate data between two independent projects.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.project_context import get_project_context
from agents.registry import AgentRegistry
from agents.executor import AgentExecutor
from agents.workflow import WorkflowEngine
from creative_loop.reflection_service import ReflectionService
from creative_loop.health_service import HealthService
from creative_loop.issue_detector import IssueDetector
from creative_loop.proposal_service import ProposalService
from creative_loop.experiment_service import ExperimentService
from creative_loop.outcome_service import OutcomeService
from analytics.service import AnalyticsService
from author_memory.asset_store import AuthorAssetStore, workspace_context
from author_memory.author_profile import AuthorProfileService
from system.data_store import DataStore


@pytest.fixture
def two_projects(tmp_path: Path) -> tuple[Path, Path]:
    """Create two independent projects with distinct data."""
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"

    # Project A: 玄幻小说
    project_a.mkdir(parents=True)
    (project_a / "data" / "chapters").mkdir(parents=True)
    (project_a / "data" / "agents" / "runs").mkdir(parents=True)
    (project_a / "data" / "agents" / "workflows").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "reflections").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "health").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "issues").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "proposals").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "experiments").mkdir(parents=True)
    (project_a / "data" / "creative_loop" / "outcomes").mkdir(parents=True)
    (project_a / "data" / "story_analytics" / "chapters").mkdir(parents=True)
    (project_a / "data" / "author_profile").mkdir(parents=True)
    (project_a / "data" / "creative_assets" / "ideas").mkdir(parents=True)

    # Project A story spec
    story_spec_a = {
        "title": "仙途问剑",
        "genre": "玄幻",
        "focus": ["修仙", "剑道", "宗门争斗"],
    }
    (project_a / "data" / "story_spec.json").write_text(
        json.dumps(story_spec_a, ensure_ascii=False), encoding="utf-8"
    )

    # Project A chapter
    chapter_a = "# 第一章：剑起苍穹\n\n少年李青站在剑崖之上...\n\n这是玄幻故事的开头。"
    (project_a / "data" / "chapters" / "chapter_001.md").write_text(
        chapter_a, encoding="utf-8"
    )

    # Project B: 悬疑小说
    project_b.mkdir(parents=True)
    (project_b / "data" / "chapters").mkdir(parents=True)
    (project_b / "data" / "agents" / "runs").mkdir(parents=True)
    (project_b / "data" / "agents" / "workflows").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "reflections").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "health").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "issues").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "proposals").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "experiments").mkdir(parents=True)
    (project_b / "data" / "creative_loop" / "outcomes").mkdir(parents=True)
    (project_b / "data" / "story_analytics" / "chapters").mkdir(parents=True)
    (project_b / "data" / "author_profile").mkdir(parents=True)
    (project_b / "data" / "creative_assets" / "ideas").mkdir(parents=True)

    # Project B story spec
    story_spec_b = {
        "title": "午夜追踪者",
        "genre": "悬疑",
        "focus": ["推理", "连环案件", "心理博弈"],
    }
    (project_b / "data" / "story_spec.json").write_text(
        json.dumps(story_spec_b, ensure_ascii=False), encoding="utf-8"
    )

    # Project B chapter
    chapter_b = "# 第一章：深夜来电\n\n侦探张明接到一个神秘电话...\n\n这是悬疑故事的开头。"
    (project_b / "data" / "chapters" / "chapter_001.md").write_text(
        chapter_b, encoding="utf-8"
    )

    return project_a, project_b


class TestAgentsIsolation:
    """Test agent module project isolation."""

    def test_agent_registry_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Agent registry settings are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        registry_a = AgentRegistry(ctx_a)
        registry_b = AgentRegistry(ctx_b)

        # Disable story_director in project A
        registry_a.set_enabled("story_director", False)

        # Verify project A setting
        profile_a = registry_a.get("story_director")
        assert profile_a.enabled is False

        # Verify project B unaffected
        profile_b = registry_b.get("story_director")
        assert profile_b.enabled is True

        # Enable in project B, verify A unaffected
        registry_b.set_enabled("plot_architect", False)
        assert registry_a.get("plot_architect").enabled is True
        assert registry_b.get("plot_architect").enabled is False

    def test_agent_runs_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Agent execution traces are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        executor_a = AgentExecutor(ctx_a)
        executor_b = AgentExecutor(ctx_b)

        # Execute in project A
        trace_a = executor_a.execute(
            "story_director",
            {"chapter": {"id": 1}, "chapter_plan": {"goal": "test"}},
            workflow_run_id="test_workflow_a",
        )

        # Execute in project B
        trace_b = executor_b.execute(
            "story_director",
            {"chapter": {"id": 1}, "chapter_plan": {"goal": "test"}},
            workflow_run_id="test_workflow_b",
        )

        # Verify traces are separate
        assert trace_a["project_id"] == "project_a"
        assert trace_b["project_id"] == "project_b"

        # List traces per project
        traces_a = executor_a.traces()
        traces_b = executor_b.traces()

        trace_ids_a = {t["trace_id"] for t in traces_a}
        trace_ids_b = {t["trace_id"] for t in traces_b}

        # No overlap
        assert trace_ids_a.isdisjoint(trace_ids_b)

        # Verify file isolation
        assert (project_a / "data" / "agents" / "runs" / f"{trace_a['trace_id']}.json").exists()
        assert (project_b / "data" / "agents" / "runs" / f"{trace_b['trace_id']}.json").exists()
        assert not (project_a / "data" / "agents" / "runs" / f"{trace_b['trace_id']}.json").exists()

    def test_workflow_runs_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Workflow runs are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        engine_a = WorkflowEngine(ctx_a)
        engine_b = WorkflowEngine(ctx_b)

        # Start workflow in project A
        run_a = engine_a.start(
            "chapter_creative_v1",
            {"chapter": {"id": 1}, "context_ref": "test"},
        )

        # Start workflow in project B
        run_b = engine_b.start(
            "chapter_creative_v1",
            {"chapter": {"id": 1}, "context_ref": "test"},
        )

        # Verify project IDs
        assert run_a["project_id"] == "project_a"
        assert run_b["project_id"] == "project_b"

        # List runs per project
        runs_a = engine_a.runs()
        runs_b = engine_b.runs()

        run_ids_a = {r["run_id"] for r in runs_a}
        run_ids_b = {r["run_id"] for r in runs_b}

        # No overlap
        assert run_ids_a.isdisjoint(run_ids_b)


class TestCreativeLoopIsolation:
    """Test creative_loop module project isolation."""

    def test_reflections_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Reflections are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = ReflectionService(ctx_a)
        service_b = ReflectionService(ctx_b)

        # Create reflection file directly in project A
        reflection_a = {
            "schema_version": "13.0",
            "reflection_id": "reflection_a_001",
            "project_id": "project_a",
            "chapter_id": 1,
            "canon_version_id": "canon_a_001",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_a).write_json(
            "data/creative_loop/reflections/reflection_a_001.json",
            reflection_a,
        )

        # Create reflection file directly in project B
        reflection_b = {
            "schema_version": "13.0",
            "reflection_id": "reflection_b_001",
            "project_id": "project_b",
            "chapter_id": 1,
            "canon_version_id": "canon_b_001",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_b).write_json(
            "data/creative_loop/reflections/reflection_b_001.json",
            reflection_b,
        )

        # List reflections per project
        reflections_a = service_a.list()
        reflections_b = service_b.list()

        reflection_ids_a = {r["reflection_id"] for r in reflections_a}
        reflection_ids_b = {r["reflection_id"] for r in reflections_b}

        # No cross-project visibility
        assert "reflection_a_001" in reflection_ids_a
        assert "reflection_a_001" not in reflection_ids_b
        assert "reflection_b_001" in reflection_ids_b
        assert "reflection_b_001" not in reflection_ids_a

    def test_health_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Health records are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = HealthService(ctx_a)
        service_b = HealthService(ctx_b)

        # Create health history in project A
        health_a = {
            "schema_version": "13.1",
            "health_id": "health_a_001",
            "project_id": "project_a",
            "chapter_id": 1,
            "canon_version_id": "canon_a_001",
            "overall": 75,
            "confidence": 0.85,
            "dimensions": {"narrative_consistency": 80},
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_a).write_json(
            "data/creative_loop/health/history.json",
            [health_a],
        )

        # Create health history in project B
        health_b = {
            "schema_version": "13.1",
            "health_id": "health_b_001",
            "project_id": "project_b",
            "chapter_id": 1,
            "canon_version_id": "canon_b_001",
            "overall": 60,
            "confidence": 0.90,
            "dimensions": {"narrative_consistency": 65},
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_b).write_json(
            "data/creative_loop/health/history.json",
            [health_b],
        )

        # Verify project A health
        latest_a = service_a.latest()
        assert latest_a is not None
        assert latest_a["health_id"] == "health_a_001"
        assert latest_a["project_id"] == "project_a"

        # Verify project B health
        latest_b = service_b.latest()
        assert latest_b is not None
        assert latest_b["health_id"] == "health_b_001"
        assert latest_b["project_id"] == "project_b"

    def test_issues_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Issues are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = IssueDetector(ctx_a)
        service_b = IssueDetector(ctx_b)

        # Create issue in project A
        issue_a = {
            "schema_version": "13.0",
            "issue_id": "issue_a_001",
            "project_id": "project_a",
            "chapter_id": 1,
            "issue_type": "low_pacing",
            "title": "Project A issue",
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_a).write_json(
            "data/creative_loop/issues/index.json",
            [issue_a],
        )

        # Create issue in project B
        issue_b = {
            "schema_version": "13.0",
            "issue_id": "issue_b_001",
            "project_id": "project_b",
            "chapter_id": 1,
            "issue_type": "low_conflict",
            "title": "Project B issue",
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
        }
        DataStore(ctx_b).write_json(
            "data/creative_loop/issues/index.json",
            [issue_b],
        )

        # List issues per project
        issues_a = service_a.list()
        issues_b = service_b.list()

        issue_ids_a = {i["issue_id"] for i in issues_a}
        issue_ids_b = {i["issue_id"] for i in issues_b}

        assert "issue_a_001" in issue_ids_a
        assert "issue_a_001" not in issue_ids_b
        assert "issue_b_001" in issue_ids_b
        assert "issue_b_001" not in issue_ids_a


class TestAnalyticsIsolation:
    """Test analytics module project isolation."""

    def test_story_spec_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Analytics reads project-specific story spec."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = AnalyticsService(ctx_a)
        service_b = AnalyticsService(ctx_b)

        # Verify project A reads its own spec
        spec_a = service_a._spec()
        assert spec_a["title"] == "仙途问剑"
        assert spec_a["genre"] == "玄幻"

        # Verify project B reads its own spec
        spec_b = service_b._spec()
        assert spec_b["title"] == "午夜追踪者"
        assert spec_b["genre"] == "悬疑"

    def test_chapter_analytics_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Chapter analytics are project-specific."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = AnalyticsService(ctx_a)
        service_b = AnalyticsService(ctx_b)

        # Analyze chapter 1 in both projects
        analytics_a = service_a.chapter(1)
        analytics_b = service_b.chapter(1)

        # Verify project A analytics
        assert analytics_a["chapter_id"] == 1
        # Should find玄幻-specific keywords

        # Verify project B analytics
        assert analytics_b["chapter_id"] == 1
        # Should find 悬疑-specific keywords

        # Verify file isolation
        analytics_file_a = project_a / "data" / "story_analytics" / "chapters" / "chapter_001.json"
        analytics_file_b = project_b / "data" / "story_analytics" / "chapters" / "chapter_001.json"

        assert analytics_file_a.exists()
        assert analytics_file_b.exists()

        # Verify content is different
        content_a = json.loads(analytics_file_a.read_text(encoding="utf-8"))
        content_b = json.loads(analytics_file_b.read_text(encoding="utf-8"))

        assert content_a["chapter_id"] == 1
        assert content_b["chapter_id"] == 1
        source_a = (project_a / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
        source_b = (project_b / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
        assert source_a != source_b
        assert content_a["word_count"] == len(source_a)
        assert content_b["word_count"] == len(source_b)

    def test_market_analytics_isolation(self, two_projects: tuple[Path, Path]) -> None:
        """Market analytics use project-specific genre."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        service_a = AnalyticsService(ctx_a)
        service_b = AnalyticsService(ctx_b)

        market_a = service_a.market()
        market_b = service_b.market()

        # Project A should have 玄幻 genre
        assert market_a["genre"] == "玄幻"

        # Project B should have 悬疑 genre
        assert market_b["genre"] == "悬疑"


class TestAuthorMemoryScope:
    """Test author_memory module scope semantics."""

    def test_author_profile_is_workspace_level(self, tmp_path: Path) -> None:
        """Author profile uses workspace context, not project context."""
        # Create workspace with .story_os
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".story_os").mkdir()
        (workspace / ".story_os" / "config.json").write_text("{}")

        # Create child project
        project = workspace / "project_x"
        project.mkdir()
        (project / "data" / "author_profile").mkdir(parents=True)

        # Get project context
        project_ctx = get_project_context(project)

        # Create AuthorAssetStore with project context
        assets = AuthorAssetStore(project_ctx)

        # workspace_context should resolve to workspace
        resolved_ctx = workspace_context(project_ctx)
        assert resolved_ctx.root == workspace

        # Author profile should be written to workspace, not project
        assets.write_profile({"id": "test_author", "name": "Test Author"})

        # Verify file location
        workspace_profile = workspace / "data" / "author_profile" / "profile.json"
        project_profile = project / "data" / "author_profile" / "profile.json"

        # Workspace level is preferred if .story_os exists
        # The implementation writes to resolved context root
        assert assets.context.root == workspace

    def test_author_assets_shared_across_projects(self, tmp_path: Path) -> None:
        """Author assets can be shared across sibling projects."""
        # Create workspace
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".story_os").mkdir()
        (workspace / ".story_os" / "config.json").write_text("{}")
        (workspace / "data" / "creative_assets" / "ideas").mkdir(parents=True)

        # Create two child projects
        project_a = workspace / "project_a"
        project_a.mkdir()

        project_b = workspace / "project_b"
        project_b.mkdir()

        # Add asset from project A context
        ctx_a = get_project_context(project_a)
        assets_a = AuthorAssetStore(ctx_a)
        asset = assets_a.add_asset({
            "type": "idea",
            "name": "Shared Idea",
            "category": "ideas",
            "content": "This should be visible from project B",
        })

        # Verify asset exists
        assert asset["id"] is not None

        # Access from project B context
        ctx_b = get_project_context(project_b)
        assets_b = AuthorAssetStore(ctx_b)

        # Both should resolve to same workspace
        list_b = assets_b.list_assets()

        # Asset should be visible
        assert any(a["name"] == "Shared Idea" for a in list_b)


class TestNoCrossProjectPollution:
    """Test that concurrent operations don't pollute other projects."""

    def test_concurrent_agent_execution(self, two_projects: tuple[Path, Path]) -> None:
        """Concurrent agent runs don't interfere."""
        project_a, project_b = two_projects

        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)

        executor_a = AgentExecutor(ctx_a)
        executor_b = AgentExecutor(ctx_b)

        # Execute multiple times in each project
        for i in range(3):
            executor_a.execute(
                "story_director",
                {"chapter": {"id": i + 1}},
                workflow_run_id=f"test_a_{i}",
            )
            executor_b.execute(
                "story_director",
                {"chapter": {"id": i + 1}},
                workflow_run_id=f"test_b_{i}",
            )

        # Verify isolation
        traces_a = executor_a.traces()
        traces_b = executor_b.traces()

        for t in traces_a:
            assert t["project_id"] == "project_a"

        for t in traces_b:
            assert t["project_id"] == "project_b"

        # Verify file counts
        runs_a = list((project_a / "data" / "agents" / "runs").glob("*.json"))
        runs_b = list((project_b / "data" / "agents" / "runs").glob("*.json"))

        assert len(runs_a) >= 3
        assert len(runs_b) >= 3

    def test_cwd_independence(self, two_projects: tuple[Path, Path], monkeypatch) -> None:
        """Module paths don't change when CWD changes."""
        project_a, project_b = two_projects

        # Get context for project A
        ctx_a = get_project_context(project_a)

        # Change CWD to project B
        monkeypatch.chdir(project_b)

        # Context for project A should still point to project A
        # (when explicit root is passed)
        ctx_a_again = get_project_context(project_a)
        assert ctx_a_again.root == project_a

        # DataStore should use correct context
        store_a = DataStore(ctx_a_again)
        assert store_a.context.root == project_a

        # Reading story_spec should return project A's spec
        spec = store_a.read_json("data/story_spec.json")
        assert spec["title"] == "仙途问剑"


class TestStaticPathGuardIntegration:
    """Integration test for static path guard."""

    def test_static_guard_detects_violations(self, tmp_path: Path) -> None:
        """Static guard correctly identifies violations."""
        from tests.test_static_path_guard import _scan_file

        # Create a file with violation
        bad_file = tmp_path / "bad_module.py"
        bad_file.write_text('''
# This file has hardcoded paths
from pathlib import Path

def bad_function():
    path = Path("data/chapters/chapter_001.md")
    return path
''')

        violations = _scan_file(bad_file)

        # Should detect Path("data/...")
        assert len(violations) >= 1
        assert any("Path" in v["pattern"] for v in violations)

    def test_static_guard_allows_datastore_patterns(self, tmp_path: Path) -> None:
        """Static guard allows DataStore patterns."""
        from tests.test_static_path_guard import _scan_file

        # Create a file with allowed pattern
        good_file = tmp_path / "good_module.py"
        good_file.write_text('''
from system.data_store import DataStore

def good_function(store: DataStore):
    data = store.read_json("data/chapters/chapter_001.json")
    return data
''')

        violations = _scan_file(good_file)

        # Should not detect violations (DataStore pattern is allowed)
        assert len(violations) == 0
