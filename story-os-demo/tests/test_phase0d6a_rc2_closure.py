"""Phase 0D6-A-RC2 seal-closure evidence."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.contracts.narrative_turn import NarrativeTurnError
from core.project_context import get_project_context
from system.chapter_lifecycle_adapters import (
    SimulatorChapterLifecycleAdapter,
    TraditionalChapterLifecycleAdapter,
)
from system.chapter_lifecycle_service import (
    BranchArchivedError,
    ChapterLifecycleError,
    ChapterLifecycleRecoveryRequiredError,
    ChapterLifecycleService,
    CommitResultInvalidError,
    OperationConflictError,
    PlanningStaleError,
)
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "chapters").mkdir(parents=True)
    (data / "versions").mkdir()
    (data / "canon_versions").mkdir()
    (data / "chapters" / "chapter_001.md").write_text("# Chapter 001\n", encoding="utf-8")
    _json(data / "state.json", {"current_chapter": 1})
    _json(data / "next_chapter_plan.json", {"chapter_id": 2, "revision": "plan-1"})
    _json(
        data / "chapter_commits" / "commit_001.json",
        {
            "schema_version": "1.0",
            "chapter_id": 1,
            "commit_id": "commit-001",
            "status": "committed",
            "source_version_id": "manual_v001",
            "canon_revision_id": "canon-001",
        },
    )
    context = get_project_context(tmp_path)
    branches = BranchLifecycleService(context)
    scope = {"project_id": context.root.name, "timeline_id": "main"}
    branches.create("branch-create-a", {**scope, "branch_id": "a"})
    branches.create("branch-create-b", {**scope, "branch_id": "b"})
    revision = branches.list_branches(**scope)["registry_revision"]
    branches.select(
        "branch-select-a",
        {**scope, "branch_id": "a", "expected_registry_revision": revision},
    )
    return tmp_path


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _assert_no_residue(root: Path) -> None:
    assert not list(root.rglob("*.tmp"))
    assert not list(root.rglob("owner.json"))
    assert not [path for path in root.rglob("*.lock") if path.is_dir()]


def _assert_no_successor(root: Path) -> None:
    assert not (root / "data/chapters/chapter_002.md").exists()
    assert not (root / "data/versions/chapter_002_versions.json").exists()
    assert not (root / "data/canon_versions/chapter_002").exists()


def _archive_a(context, operation_id: str = "archive-a") -> dict:
    branch = BranchLifecycleService(context)
    revision = branch.list_branches(context.root.name, "main")["registry_revision"]
    return branch.archive(
        operation_id,
        {
            "project_id": context.root.name,
            "timeline_id": "main",
            "branch_id": "a",
            "replacement_branch_id": "b",
            "expected_registry_revision": revision,
        },
    )


@pytest.mark.parametrize("mutation", ["content", "revision", "delete", "replace"])
def test_planning_authority_changes_fail_closed_without_orphans(tmp_path: Path, mutation: str):
    root = _project(tmp_path)
    plan = root / "data/next_chapter_plan.json"

    def fault(point: str) -> None:
        if point != "after_staging_creation":
            return
        if mutation == "delete":
            plan.unlink()
        elif mutation == "replace":
            _json(plan, {"chapter_id": 99, "revision": "replacement"})
        else:
            payload = json.loads(plan.read_text(encoding="utf-8"))
            payload[mutation] = "changed"
            _json(plan, payload)

    service = ChapterLifecycleService(get_project_context(root), fault_injector=fault)
    with pytest.raises(PlanningStaleError):
        service.create_next_chapter(
            operation_id=f"planning-{mutation}",
            expected_active_branch_id="a",
            planning_chapter_id=2,
        )
    _assert_no_successor(root)
    _assert_no_residue(root)


@pytest.mark.parametrize("mutation", ["bytes", "delete", "corrupt", "recovery", "warning"])
def test_completion_authority_changes_fail_closed_without_orphans(tmp_path: Path, mutation: str):
    root = _project(tmp_path)
    commit = root / "data/chapter_commits/commit_001.json"

    def fault(point: str) -> None:
        if point != "after_canon_init":
            return
        if mutation == "delete":
            commit.unlink()
        elif mutation == "corrupt":
            commit.write_text("{", encoding="utf-8")
        else:
            payload = json.loads(commit.read_text(encoding="utf-8"))
            if mutation == "recovery":
                payload["status"] = "recovery_required"
            elif mutation == "warning":
                payload["status"] = "committed_with_warnings"
            else:
                payload["source_version_id"] = "manual_v002"
            _json(commit, payload)

    service = ChapterLifecycleService(get_project_context(root), fault_injector=fault)
    with pytest.raises(ChapterLifecycleError):
        service.create_next_chapter(
            operation_id=f"completion-{mutation}",
            expected_active_branch_id="a",
        )
    _assert_no_successor(root)
    _assert_no_residue(root)


def test_branch_change_after_staging_fails_closed_without_orphans(tmp_path: Path):
    root = _project(tmp_path)
    registry = root / "data/branches/main/registry.json"

    def fault(point: str) -> None:
        if point == "after_staging_creation":
            payload = json.loads(registry.read_text(encoding="utf-8"))
            payload.update({"active_branch_id": "b", "revision": "archive-revision"})
            _json(registry, payload)

    with pytest.raises(BranchArchivedError):
        ChapterLifecycleService(
            get_project_context(root), fault_injector=fault
        ).create_next_chapter(
            operation_id="branch-stale",
            expected_active_branch_id="a",
        )
    _assert_no_successor(root)


@pytest.mark.parametrize("authority_kind", ["planning", "completion"])
def test_authority_change_thread_race_fails_closed(
    tmp_path: Path, authority_kind: str
):
    root = _project(tmp_path)
    context = get_project_context(root)
    barrier = threading.Barrier(2)
    changed = threading.Event()
    failures: list[BaseException] = []

    def fault(point: str) -> None:
        if point == "after_staging_creation":
            barrier.wait(timeout=5)
            assert changed.wait(timeout=5)

    def mutate() -> None:
        try:
            barrier.wait(timeout=5)
            if authority_kind == "planning":
                _json(
                    root / "data/next_chapter_plan.json",
                    {"chapter_id": 2, "revision": "plan-raced"},
                )
            else:
                path = root / "data/chapter_commits/commit_001.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["source_version_id"] = "manual_raced"
                _json(path, payload)
            changed.set()
        except BaseException as exc:
            failures.append(exc)

    modifier = threading.Thread(target=mutate)
    modifier.start()
    with pytest.raises(ChapterLifecycleError):
        ChapterLifecycleService(context, fault_injector=fault).create_next_chapter(
            operation_id=f"authority-race-{authority_kind}",
            expected_active_branch_id="a",
        )
    modifier.join(timeout=10)
    assert not modifier.is_alive()
    assert not failures
    _assert_no_successor(root)


def test_incomplete_create_blocks_branch_archive_until_recovery(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)

    def fault(point: str) -> None:
        if point == "after_claim":
            raise ChapterLifecycleRecoveryRequiredError("injected")

    with pytest.raises(ChapterLifecycleRecoveryRequiredError):
        ChapterLifecycleService(context, fault_injector=fault).create_next_chapter(
            operation_id="create-incomplete", expected_active_branch_id="a"
        )
    branch = BranchLifecycleService(context)
    revision = branch.list_branches(context.root.name, "main")["registry_revision"]
    with pytest.raises(NarrativeTurnError) as caught:
        branch.archive(
            "archive-blocked",
            {
                "project_id": context.root.name,
                "timeline_id": "main",
                "branch_id": "a",
                "replacement_branch_id": "b",
                "expected_registry_revision": revision,
            },
        )
    assert caught.value.code == NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED
    result = ChapterLifecycleService(context).create_next_chapter(
        operation_id="create-incomplete", expected_active_branch_id="a"
    )
    assert result["status"] == "CHAPTER_CREATED"


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_claim",
        "after_successor_resolution",
        "after_staging_creation",
        "after_version_init",
        "after_canon_init",
        "after_publish",
    ],
)
def test_archive_is_blocked_at_each_incomplete_create_phase(
    tmp_path: Path, fault_point: str
):
    root = _project(tmp_path)
    context = get_project_context(root)

    def fault(point: str) -> None:
        if point == fault_point:
            raise ChapterLifecycleRecoveryRequiredError(point)

    with pytest.raises(ChapterLifecycleRecoveryRequiredError):
        ChapterLifecycleService(context, fault_injector=fault).create_next_chapter(
            operation_id=f"incomplete-{fault_point}", expected_active_branch_id="a"
        )
    with pytest.raises(NarrativeTurnError) as caught:
        _archive_a(context, f"archive-{fault_point}")
    assert caught.value.code == NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED
    ChapterLifecycleService(context).create_next_chapter(
        operation_id=f"incomplete-{fault_point}", expected_active_branch_id="a"
    )
    _assert_no_residue(root)


def test_archive_first_makes_later_create_fail_without_mutation(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)
    _archive_a(context)
    before = _snapshot(root)
    with pytest.raises(ChapterLifecycleError):
        ChapterLifecycleService(context).create_next_chapter(
            operation_id="create-after-archive", expected_active_branch_id="a"
        )
    assert _snapshot(root) == before
    _assert_no_successor(root)


def test_completed_create_then_archive_has_two_ordered_durable_results(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)
    created = ChapterLifecycleService(context).create_next_chapter(
        operation_id="create-before-archive", expected_active_branch_id="a"
    )
    archived = _archive_a(context)
    replay = ChapterLifecycleService(context).create_next_chapter(
        operation_id="create-before-archive", expected_active_branch_id="a"
    )
    assert created == replay
    assert archived["branch"]["lifecycle_status"] == "archived"
    assert (root / "data/chapters/chapter_002.md").exists()


def test_archive_crash_retry_wins_before_later_create(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)

    def fault(point: str) -> None:
        if point == "after_archive":
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED, "injected"
            )

    branch = BranchLifecycleService(context, fault_injector=fault)
    revision = branch.list_branches(context.root.name, "main")["registry_revision"]
    values = {
        "project_id": context.root.name,
        "timeline_id": "main",
        "branch_id": "a",
        "replacement_branch_id": "b",
        "expected_registry_revision": revision,
    }
    with pytest.raises(NarrativeTurnError):
        branch.archive("archive-crash", values)
    with pytest.raises(ChapterLifecycleError):
        ChapterLifecycleService(context).create_next_chapter(
            operation_id="create-after-archive-crash",
            expected_active_branch_id="a",
        )
    recovered = BranchLifecycleService(context).archive("archive-crash", values)
    assert recovered["branch"]["lifecycle_status"] == "archived"
    _assert_no_successor(root)


def test_create_archive_barrier_has_one_serial_authority_order(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def create() -> None:
        barrier.wait(timeout=5)
        try:
            ChapterLifecycleService(context).create_next_chapter(
                operation_id="race-create", expected_active_branch_id="a"
            )
            outcomes.append("create")
        except ChapterLifecycleError:
            outcomes.append("create-stale")

    def archive() -> None:
        branch = BranchLifecycleService(context)
        revision = branch.list_branches(context.root.name, "main")["registry_revision"]
        barrier.wait(timeout=5)
        try:
            branch.archive(
                "race-archive",
                {
                    "project_id": context.root.name,
                    "timeline_id": "main",
                    "branch_id": "a",
                    "replacement_branch_id": "b",
                    "expected_registry_revision": revision,
                },
            )
            outcomes.append("archive")
        except NarrativeTurnError:
            outcomes.append("archive-blocked")

    threads = [threading.Thread(target=create), threading.Thread(target=archive)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(outcomes) == 2
    assert not ("create-stale" not in outcomes and "archive-blocked" in outcomes)
    _assert_no_residue(root)


def test_success_filesystem_diff_is_allowlisted_and_staging_is_cleaned(tmp_path: Path):
    root = _project(tmp_path)
    before = _snapshot(root)
    ChapterLifecycleService(get_project_context(root)).create_next_chapter(
        operation_id="fs-success", expected_active_branch_id="a"
    )
    after = _snapshot(root)
    changed = set(after) ^ set(before)
    changed.update(path for path in before.keys() & after.keys() if before[path] != after[path])
    assert changed == {
        "data/chapter_lifecycle/operations/fs-success.json",
        "data/chapter_lifecycle/operations/fs-success.phase.json",
        "data/chapter_lifecycle/operations/fs-success.result.json",
        "data/chapters/chapter_002.md",
        "data/versions/chapter_002_versions.json",
            "data/canon_versions/chapter_002/canon_v001.md",
            "data/canon_versions/chapter_002/index.json",
            "data/narrative_memory/continuity/main/a/chapter_001_to_002.json",
        }
    _assert_no_residue(root)


def test_replay_and_conflict_have_zero_successor_filesystem_diff(tmp_path: Path):
    root = _project(tmp_path)
    service = ChapterLifecycleService(get_project_context(root))
    values = {"operation_id": "stable-replay", "expected_active_branch_id": "a"}
    service.create_next_chapter(**values)
    before = _snapshot(root)
    service.create_next_chapter(**values)
    assert _snapshot(root) == before
    with pytest.raises(OperationConflictError):
        service.create_next_chapter(**{**values, "planning_chapter_id": 2})
    assert _snapshot(root) == before


@pytest.mark.parametrize("failure", ["version", "canon", "publication"])
def test_initialization_and_publication_failures_leave_no_orphans(
    tmp_path: Path, monkeypatch, failure: str
):
    root = _project(tmp_path)
    import system.chapter_lifecycle_service as module

    if failure == "version":
        def fail_version(chapter_id, data_dir):
            (Path(data_dir) / "versions" / f"chapter_{chapter_id:03d}_versions.json").write_text("{}", encoding="utf-8")
            raise OSError("version failure")
        monkeypatch.setattr(module, "initialize_chapter_versions", fail_version)
    elif failure == "canon":
        original = ChapterLifecycleService.initialize_chapter_canon
        def fail_canon(self, chapter_id, content):
            path = self.context.data_dir / "canon_versions" / f"chapter_{chapter_id:03d}"
            path.mkdir(parents=True)
            (path / "partial").write_text("partial", encoding="utf-8")
            raise OSError("canon failure")
        monkeypatch.setattr(ChapterLifecycleService, "initialize_chapter_canon", fail_canon)
    else:
        monkeypatch.setattr(module, "_publish_if_absent", lambda path, content: False)

    with pytest.raises(ChapterLifecycleError):
        ChapterLifecycleService(get_project_context(root)).create_next_chapter(
            operation_id=f"failure-{failure}", expected_active_branch_id="a"
        )
    _assert_no_successor(root)
    _assert_no_residue(root)


def test_durable_result_write_failure_recovers_without_second_publication(
    tmp_path: Path, monkeypatch
):
    root = _project(tmp_path)
    import system.chapter_lifecycle_service as module

    original = module._atomic_json
    failed = False

    def fail_result_once(path: Path, payload: dict) -> None:
        nonlocal failed
        if path.name == "result-failure.result.json" and not failed:
            failed = True
            raise OSError("result failure")
        original(path, payload)

    monkeypatch.setattr(module, "_atomic_json", fail_result_once)
    context = get_project_context(root)
    with pytest.raises(ChapterLifecycleRecoveryRequiredError):
        ChapterLifecycleService(context).create_next_chapter(
            operation_id="result-failure", expected_active_branch_id="a"
        )
    assert (root / "data/chapters/chapter_002.md").exists()
    monkeypatch.setattr(module, "_atomic_json", original)
    recovered = ChapterLifecycleService(context).create_next_chapter(
        operation_id="result-failure", expected_active_branch_id="a"
    )
    assert recovered["status"] == "CHAPTER_CREATED"
    assert len(list((root / "data/chapters").glob("chapter_002.md"))) == 1
    _assert_no_residue(root)


def test_stale_and_failed_lock_owner_artifacts_are_cleaned(
    tmp_path: Path, monkeypatch
):
    root = _project(tmp_path)
    context = get_project_context(root)
    service = ChapterLifecycleService(context)
    stale = service._lock_path("main:authority")
    stale.mkdir(parents=True)
    (stale / "owner.json").write_text("{", encoding="utf-8")
    old = time.time() - 5
    os.utime(stale, (old, old))
    service.create_next_chapter(
        operation_id="stale-lock", expected_active_branch_id="a"
    )
    _assert_no_residue(root)

    second = _project(tmp_path / "owner-write-failure")
    second_service = ChapterLifecycleService(get_project_context(second))
    import system.chapter_lifecycle_service as module
    original = module._atomic_json

    def fail_owner(path: Path, payload: dict) -> None:
        if path.name == "owner.json":
            raise OSError("owner write failed")
        original(path, payload)

    monkeypatch.setattr(module, "_atomic_json", fail_owner)
    with pytest.raises(OSError):
        second_service.create_next_chapter(
            operation_id="owner-failure", expected_active_branch_id="a"
        )
    assert not second_service._lock_path("main:authority").exists()


def test_cross_project_and_cross_timeline_fail_before_mutation(tmp_path: Path):
    root = _project(tmp_path / "project-a")
    other = _project(tmp_path / "project-b")
    before_root = _snapshot(root)
    before_other = _snapshot(other)
    service = ChapterLifecycleService(get_project_context(root))
    with pytest.raises(ChapterLifecycleError):
        service.create_next_chapter(operation_id="cross-project", project_id="project-b")
    with pytest.raises(ChapterLifecycleError):
        service.create_next_chapter(operation_id="cross-timeline", timeline_id="other")
    assert _snapshot(root) == before_root
    assert _snapshot(other) == before_other


def test_adapters_share_one_durable_result_and_conflict_on_changed_request(tmp_path: Path):
    root = _project(tmp_path)
    context = get_project_context(root)
    traditional = TraditionalChapterLifecycleAdapter(context)
    simulator = SimulatorChapterLifecycleAdapter(context)
    values = {
        "operation_id": "adapter-shared",
        "project_id": context.root.name,
        "expected_active_branch_id": "a",
    }
    first = traditional.create(**values)
    second = simulator.create(**values)
    assert first == second
    with pytest.raises(OperationConflictError):
        simulator.create(**{**values, "planning_chapter_id": 2})


def test_route_replay_is_exactly_once_and_invalid_input_writes_nothing(
    tmp_path: Path, monkeypatch
):
    root = _project(tmp_path)
    monkeypatch.chdir(root)
    from web.app import app

    before = _snapshot(root)
    with TestClient(app) as client:
        invalid = client.post(
            "/api/chapter-lifecycle/next",
            json={"operation_id": "../bad", "project_id": root.name, "source": "traditional"},
        )
        assert invalid.status_code == 422
        assert _snapshot(root) == before
        payload = {
            "operation_id": "route-replay",
            "project_id": root.name,
            "timeline_id": "main",
            "expected_active_branch_id": "a",
            "source": "traditional",
        }
        first = client.post("/api/chapter-lifecycle/next", json=payload)
        payload["source"] = "simulator"
        second = client.post("/api/chapter-lifecycle/next", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["result"] == second.json()["result"]
    assert len(list((root / "data/chapters").glob("chapter_002.md"))) == 1
    _assert_no_residue(root)
