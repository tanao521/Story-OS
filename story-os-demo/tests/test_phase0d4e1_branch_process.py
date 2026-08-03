from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from core.project_context import get_project_context
from core.contracts.narrative_turn import NarrativeTurnError, TimelineContext
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_real_processes_competing_select_have_one_revision_winner(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    service.create("proc-create-a", {**scope, "branch_id": "a"})
    service.create("proc-create-b", {**scope, "branch_id": "b"})
    revision = service.list_branches(**scope)["registry_revision"]
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
import json, sys
root=sys.argv[1]; ctx=get_project_context(root); s=BranchLifecycleService(ctx)
try:
    result=s.select(sys.argv[2], {'project_id':ctx.root.name,'timeline_id':'main','branch_id':sys.argv[3],'expected_registry_revision':sys.argv[4]})
    print(json.dumps({'ok':True,'active':result['active_branch_id']}))
except Exception as exc:
    print(json.dumps({'ok':False,'code':getattr(exc,'code','INTERNAL_ERROR'),'error':repr(exc)}))
"""
    processes = [
        subprocess.Popen([sys.executable, "-c", child, str(tmp_path), "proc-select-a", "a", revision], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env()),
        subprocess.Popen([sys.executable, "-c", child, str(tmp_path), "proc-select-b", "b", revision], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env()),
    ]
    outputs = []
    for proc in processes:
        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, stderr
        outputs.append(json.loads(stdout.strip()))
    assert sum(item["ok"] for item in outputs) == 1
    final = BranchLifecycleService(ctx).list_branches(**scope)
    active = next(item for item in final["branches"] if item["is_active"])
    assert active["lifecycle_status"] == "open"


def test_killed_process_lock_is_reclaimed(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    signal = tmp_path / "lock-acquired.signal"
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from pathlib import Path
import sys, time
ctx=get_project_context(sys.argv[1]); s=BranchLifecycleService(ctx)
with s._registry_lock('main'):
    Path(sys.argv[2]).write_text('ready', encoding='utf-8')
    time.sleep(30)
"""
    proc = subprocess.Popen([sys.executable, "-c", child, str(tmp_path), str(signal)], env=_child_env())
    for _ in range(100):
        if signal.exists():
            break
        time.sleep(0.05)
    assert signal.exists()
    proc.kill()
    proc.wait(timeout=10)
    result = BranchLifecycleService(ctx).create("after-kill", {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "after"})
    assert result["branch"]["branch_id"] == "after"


def _run_processes(tmp_path: Path, child: str, args: list[str]) -> list[dict]:
    processes = [
        subprocess.Popen([sys.executable, "-c", child, str(tmp_path), *item], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env())
        for item in args
    ]
    results = []
    for proc in processes:
        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, stderr
        results.append(json.loads(stdout.strip()))
    return results


def test_real_process_select_vs_active_archive_has_one_registry_winner(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    for branch_id in ("a", "b", "c"):
        service.create(f"seed-{branch_id}", {**scope, "branch_id": branch_id})
    revision = service.list_branches(**scope)["registry_revision"]
    service.select("seed-active", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
import json, sys
ctx=get_project_context(sys.argv[1]); s=BranchLifecycleService(ctx); scope={'project_id':ctx.root.name,'timeline_id':'main','expected_registry_revision':sys.argv[5]}
try:
    if sys.argv[2] == 'select': result=s.select(sys.argv[3], {**scope,'branch_id':'b'})
    else: result=s.archive(sys.argv[3], {**scope,'branch_id':'a','replacement_branch_id':'c'})
    print(json.dumps({'ok':True,'active':result['active_branch_id']}))
except Exception as exc:
    print(json.dumps({'ok':False,'code':getattr(exc,'code','INTERNAL_ERROR')}))
"""
    results = _run_processes(tmp_path, child, [["select", "race-select", "b", revision], ["archive", "race-archive", "a", revision]])
    assert sum(item["ok"] for item in results) == 1, results
    final = BranchLifecycleService(ctx).list_branches(**scope)
    active = next(item for item in final["branches"] if item["is_active"])
    assert active["lifecycle_status"] == "open"
    assert active["branch_id"] in {"b", "c"}
    target = next(item for item in final["branches"] if item["branch_id"] == "a")
    if active["branch_id"] == "c":
        assert target["lifecycle_status"] == "archived"
    else:
        assert target["lifecycle_status"] == "open"
    if target["lifecycle_status"] == "archived":
        assert len(BranchLifecycleService(ctx).store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "a")) == 1
    journal = sorted((ctx.data_dir / "branches" / "main" / "registry_events").glob("*.json"))
    assert [path.stem for path in journal] == [f"{index:08d}" for index in range(len(journal))]


def test_real_process_competing_active_archives_have_one_winner(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    for branch_id in ("a", "b", "c"):
        service.create(f"seed-{branch_id}", {**scope, "branch_id": branch_id})
    revision = service.list_branches(**scope)["registry_revision"]
    service.select("seed-active", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
import json, sys
ctx=get_project_context(sys.argv[1]); s=BranchLifecycleService(ctx)
try:
    result=s.archive(sys.argv[2], {'project_id':ctx.root.name,'timeline_id':'main','branch_id':'a','replacement_branch_id':sys.argv[3],'expected_registry_revision':sys.argv[4]})
    print(json.dumps({'ok':True,'active':result['active_branch_id']}))
except Exception as exc:
    print(json.dumps({'ok':False,'code':getattr(exc,'code','INTERNAL_ERROR')}))
"""
    results = _run_processes(tmp_path, child, [["race-archive-b", "b", revision], ["race-archive-c", "c", revision]])
    assert sum(item["ok"] for item in results) == 1, results
    final = BranchLifecycleService(ctx).list_branches(**scope)
    active = next(item for item in final["branches"] if item["is_active"])
    assert active["branch_id"] in {"b", "c"}
    assert active["lifecycle_status"] == "open"
    assert next(item for item in final["branches"] if item["branch_id"] == "a")["lifecycle_status"] == "archived"
    assert all(item["lifecycle_status"] == "open" for item in final["branches"] if item["branch_id"] in {"b", "c"} and item["branch_id"] != active["branch_id"])
    assert len(BranchLifecycleService(ctx).store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "a")) == 1


def test_live_pid_with_reused_identity_is_not_treated_as_owner(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    lock = service._lock_path("main")
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "nonce": "old", "process_start_identity": "different-process"}), encoding="utf-8")
    result = service.create("pid-reuse", {"project_id": ctx.root.name, "timeline_id": "main", "branch_id": "pid-reuse"})
    assert result["branch"]["branch_id"] == "pid-reuse"
    owner = json.loads((service._lock_path("main") / "owner.json").read_text(encoding="utf-8")) if service._lock_path("main").exists() else None
    assert owner is None


def test_real_process_restore_vs_select_keeps_lifecycle_and_activity_separate(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    for branch_id in ("a", "b", "c"):
        service.create(f"seed-{branch_id}", {**scope, "branch_id": branch_id})
    revision = service.list_branches(**scope)["registry_revision"]
    service.select("seed-active", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    service.archive("seed-archive", {**scope, "branch_id": "b", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
import json, sys
ctx=get_project_context(sys.argv[1]); s=BranchLifecycleService(ctx)
try:
    if sys.argv[2] == 'restore': result=s.restore(sys.argv[3], {'project_id':ctx.root.name,'timeline_id':'main','branch_id':'b','expected_registry_revision':sys.argv[5]})
    else: result=s.select(sys.argv[3], {'project_id':ctx.root.name,'timeline_id':'main','branch_id':'c','expected_registry_revision':sys.argv[5]})
    print(json.dumps({'ok':True,'active':result['active_branch_id']}))
except Exception as exc:
    print(json.dumps({'ok':False,'code':getattr(exc,'code','INTERNAL_ERROR')}))
"""
    results = _run_processes(tmp_path, child, [["restore", "race-restore", "b", revision], ["select", "race-select-c", "c", revision]])
    assert all(item["ok"] for item in results), results
    final = BranchLifecycleService(ctx).list_branches(**scope)
    branch_b = next(item for item in final["branches"] if item["branch_id"] == "b")
    assert branch_b["lifecycle_status"] == "open"
    assert branch_b["is_active"] is False
    active = next(item for item in final["branches"] if item["is_active"])
    assert active["branch_id"] in {"a", "c"}
    assert len(BranchLifecycleService(ctx).store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "b")) == 2


def _setup_restore_select_ordering(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    scope = {"project_id": ctx.root.name, "timeline_id": "main"}
    for branch_id in ("a", "b", "c"):
        service.create(f"seed-{branch_id}", {**scope, "branch_id": branch_id})
    revision = service.list_branches(**scope)["registry_revision"]
    service.select("seed-active", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    revision = service.list_branches(**scope)["registry_revision"]
    service.archive("seed-archive", {**scope, "branch_id": "b", "expected_registry_revision": revision})
    return ctx, service, scope, service.list_branches(**scope)["registry_revision"]


def test_select_then_restore_accepts_original_activity_revision(tmp_path: Path):
    ctx, service, scope, revision = _setup_restore_select_ordering(tmp_path)

    service.select("ordered-select", {**scope, "branch_id": "c", "expected_registry_revision": revision})
    service.restore("ordered-restore", {**scope, "branch_id": "b", "expected_registry_revision": revision})

    final = service.list_branches(**scope)
    branch_b = next(item for item in final["branches"] if item["branch_id"] == "b")
    assert branch_b["lifecycle_status"] == "open"
    assert branch_b["is_active"] is False
    assert final["active_branch_id"] == "c"
    assert len(service.store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "b")) == 2


def test_restore_then_select_accepts_original_activity_revision(tmp_path: Path):
    ctx, service, scope, revision = _setup_restore_select_ordering(tmp_path)

    service.restore("ordered-restore", {**scope, "branch_id": "b", "expected_registry_revision": revision})
    service.select("ordered-select", {**scope, "branch_id": "c", "expected_registry_revision": revision})

    final = service.list_branches(**scope)
    branch_b = next(item for item in final["branches"] if item["branch_id"] == "b")
    assert branch_b["lifecycle_status"] == "open"
    assert branch_b["is_active"] is False
    assert final["active_branch_id"] == "c"
    assert len(service.store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "b")) == 2


def test_competing_restore_operation_still_fails_closed(tmp_path: Path):
    _, service, scope, revision = _setup_restore_select_ordering(tmp_path)
    values = {**scope, "branch_id": "b", "expected_registry_revision": revision}

    service.restore("restore-winner", values)
    with pytest.raises(NarrativeTurnError) as exc_info:
        service.restore("restore-loser", values)

    assert exc_info.value.code == NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION


def test_restore_rejects_non_selection_registry_drift(tmp_path: Path):
    _, service, scope, revision = _setup_restore_select_ordering(tmp_path)

    service.archive(
        "archive-active",
        {**scope, "branch_id": "a", "replacement_branch_id": "c", "expected_registry_revision": revision},
    )
    with pytest.raises(NarrativeTurnError) as exc_info:
        service.restore(
            "restore-after-active-archive",
            {**scope, "branch_id": "b", "expected_registry_revision": revision},
        )

    assert exc_info.value.code == NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION


def test_restore_replay_does_not_duplicate_lifecycle_event(tmp_path: Path):
    ctx, service, scope, revision = _setup_restore_select_ordering(tmp_path)
    values = {**scope, "branch_id": "b", "expected_registry_revision": revision}

    service.restore("restore-replay", values)
    replay = service.restore("restore-replay", values)

    assert replay["idempotent_replay"] is True
    events = service.store.get_lifecycle_events(TimelineContext(project_id=ctx.root.name, timeline_id="main"), "b")
    assert len(events) == 2


def test_real_processes_different_timelines_use_independent_locks(tmp_path: Path):
    ctx = get_project_context(tmp_path)
    service = BranchLifecycleService(ctx)
    project_id = ctx.root.name
    service.create("seed-main", {"project_id": project_id, "timeline_id": "main", "branch_id": "main-a"})
    (ctx.data_dir / "branches" / "other").mkdir(parents=True, exist_ok=True)
    service.create("seed-other", {"project_id": project_id, "timeline_id": "other", "branch_id": "other-a"})
    child = """
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
import json, sys
ctx=get_project_context(sys.argv[1]); s=BranchLifecycleService(ctx)
try:
    result=s.create(sys.argv[2], {'project_id':ctx.root.name,'timeline_id':sys.argv[3],'branch_id':sys.argv[4]})
    print(json.dumps({'ok':True,'timeline':sys.argv[3]}))
except Exception as exc:
    print(json.dumps({'ok':False,'code':getattr(exc,'code','INTERNAL_ERROR'),'error':repr(exc)}))
"""
    results = _run_processes(tmp_path, child, [["parallel-main", "main", "main-b"], ["parallel-other", "other", "other-b"]])
    assert all(item["ok"] for item in results), results
    assert {item["timeline"] for item in results} == {"main", "other"}
    for timeline in ("main", "other"):
        events = sorted((ctx.data_dir / "branches" / timeline / "registry_events").glob("*.json"))
        assert events
