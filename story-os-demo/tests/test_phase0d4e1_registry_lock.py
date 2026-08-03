from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from core.contracts.narrative_turn import NarrativeTurnError
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def _service(tmp_path: Path, fault_injector=None) -> BranchLifecycleService:
    return BranchLifecycleService(get_project_context(tmp_path), fault_injector=fault_injector)


def _owner(service: BranchLifecycleService, **values) -> dict:
    return {
        "pid": values.get("pid", os.getpid()),
        "nonce": values.get("nonce", "test-owner"),
        "process_start_identity": values.get(
            "process_start_identity", service._process_start_identity(os.getpid())
        ),
        "state": values.get("state", "held"),
    }


def _write_lock(service: BranchLifecycleService, owner) -> Path:
    lock = service._lock_path("main")
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    return lock


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _released_owner(service: BranchLifecycleService, nonce: str = "released-owner") -> dict:
    return _owner(service, nonce=nonce, state="released")


def _claim(service: BranchLifecycleService, lock: Path, owner: dict, **values) -> dict:
    return {
        "schema_version": "1.0",
        "lock_identity": values.get("lock_identity", service._lock_identity(lock)),
        "owner_fingerprint": values.get(
            "owner_fingerprint",
            __import__("system.narrative_branch_lifecycle_service", fromlist=["_fingerprint"])._fingerprint(owner),
        ),
        "owner_nonce": values.get("owner_nonce", owner["nonce"]),
        "claim_nonce": values.get("claim_nonce", "orphan-claim"),
        "pid": values.get("pid", 2_147_483_647),
        "process_start_identity": values.get("process_start_identity", "dead-claimer"),
    }


def _spawn_crashing_reclaimer(tmp_path: Path, exit_point: str) -> subprocess.Popen:
    child = """
import json, os, sys
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
ctx=get_project_context(sys.argv[1])
point=sys.argv[2]
def crash(actual):
    if actual == point:
        os._exit(73)
s=BranchLifecycleService(ctx, fault_injector=crash)
lock=s._lock_path('main')
owner=json.loads((lock/'owner.json').read_text(encoding='utf-8'))
s._retire_lock_directory(lock, owner)
"""
    return subprocess.Popen(
        [sys.executable, "-c", child, str(tmp_path), exit_point],
        env=_child_env(),
    )


def test_normal_release_removes_authoritative_directory(tmp_path: Path):
    service = _service(tmp_path)
    lock = service._lock_path("main")
    with service._registry_lock("main"):
        assert lock.is_dir()
    assert not lock.exists()


@pytest.mark.parametrize(
    "point",
    ["registry_lock_owner_unlink", "registry_lock_directory_rmdir"],
)
def test_transient_cleanup_failure_still_completes_release(tmp_path: Path, point: str):
    calls = 0

    def inject(actual: str) -> None:
        nonlocal calls
        if actual == point:
            calls += 1
            if calls == 1:
                raise OSError("transient cleanup failure")

    service = _service(tmp_path, inject)
    lock = service._lock_path("main")
    with service._registry_lock("main"):
        pass
    assert calls >= 2
    assert not lock.exists()


def test_released_owner_is_reclaimed_after_handoff_failures(tmp_path: Path):
    def fail_handoff(point: str) -> None:
        if point == "registry_lock_handoff":
            raise OSError("handoff unavailable")

    first = _service(tmp_path, fail_handoff)
    lock = first._lock_path("main")
    with first._registry_lock("main"):
        pass
    assert json.loads((lock / "owner.json").read_text(encoding="utf-8"))["state"] == "released"

    second = _service(tmp_path)
    with second._registry_lock("main", timeout=0.5):
        assert json.loads((lock / "owner.json").read_text(encoding="utf-8"))["state"] == "held"
    assert not lock.exists()


def test_dead_owner_is_reclaimed(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(
        service,
        _owner(service, pid=2_147_483_647, process_start_identity="dead-process"),
    )
    with service._registry_lock("main", timeout=0.5):
        assert json.loads((lock / "owner.json").read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert not lock.exists()


def test_pid_reuse_identity_mismatch_is_reclaimed(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _owner(service, process_start_identity="different-process"))
    with service._registry_lock("main", timeout=0.5):
        assert json.loads((lock / "owner.json").read_text(encoding="utf-8"))["nonce"] != "test-owner"
    assert not lock.exists()


def test_live_cross_process_owner_is_not_reclaimed(tmp_path: Path):
    signal = tmp_path / "ready"
    child = """
from pathlib import Path
import sys, time
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
s=BranchLifecycleService(get_project_context(sys.argv[1]))
with s._registry_lock('main'):
    Path(sys.argv[2]).write_text('ready', encoding='utf-8')
    time.sleep(2)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.Popen([sys.executable, "-c", child, str(tmp_path), str(signal)], env=env)
    try:
        for _ in range(100):
            if signal.exists():
                break
            time.sleep(0.02)
        assert signal.exists()
        with pytest.raises(NarrativeTurnError) as caught:
            with _service(tmp_path)._registry_lock("main", timeout=0.05):
                pass
        assert caught.value.code == NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_same_process_other_thread_is_not_reclaimed(tmp_path: Path):
    service = _service(tmp_path)
    acquired = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with service._registry_lock("main"):
            acquired.set()
            release.wait(2)

    thread = threading.Thread(target=holder)
    thread.start()
    assert acquired.wait(1)
    try:
        with pytest.raises(NarrativeTurnError):
            with _service(tmp_path)._registry_lock("main", timeout=0.05):
                pass
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_owner_publication_window_is_fail_closed(tmp_path: Path):
    entered = threading.Event()
    proceed = threading.Event()

    def pause(point: str) -> None:
        if point == "before_registry_lock_owner_publish":
            entered.set()
            assert proceed.wait(2)

    holder = _service(tmp_path, pause)

    def acquire() -> None:
        with holder._registry_lock("main"):
            pass

    thread = threading.Thread(target=acquire)
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(NarrativeTurnError):
            with _service(tmp_path)._registry_lock("main", timeout=0.05):
                pass
    finally:
        proceed.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize("contents", [None, "not-json", "[]"])
def test_ownerless_or_corrupt_directory_fails_closed(tmp_path: Path, contents: str | None):
    service = _service(tmp_path)
    lock = service._lock_path("main")
    lock.mkdir(parents=True)
    if contents is not None:
        (lock / "owner.json").write_text(contents, encoding="utf-8")
    with pytest.raises(NarrativeTurnError) as caught:
        with service._registry_lock("main", timeout=0.03):
            pass
    assert caught.value.code == NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED
    assert lock.exists()


def test_different_timelines_have_independent_locks(tmp_path: Path):
    service = _service(tmp_path)
    with service._registry_lock("main"):
        with service._registry_lock("other", timeout=0.05):
            assert service._lock_path("main") != service._lock_path("other")


def test_thread_contention_never_has_two_critical_section_owners(tmp_path: Path):
    state_lock = threading.Lock()
    active = 0
    maximum = 0
    mutations: list[int] = []

    def mutate(index: int) -> None:
        nonlocal active, maximum
        service = _service(tmp_path)
        with service._registry_lock("main", timeout=2):
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.001)
            mutations.append(index)
            with state_lock:
                active -= 1

    for _ in range(100):
        mutations.clear()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(mutate, range(8)))
        assert sorted(mutations) == list(range(8))
    assert maximum == 1


def test_orphan_claim_after_claimer_process_death_is_recovered(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _released_owner(service))
    proc = _spawn_crashing_reclaimer(tmp_path, "after_registry_reclaim_claim_publish")
    assert proc.wait(timeout=10) == 73
    assert (lock / "reclaim.claim").exists()

    with _service(tmp_path)._registry_lock("main", timeout=1):
        pass
    assert not lock.exists()


def test_live_claim_claimer_is_not_replaced(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _released_owner(service))
    child = """
import json, sys, time
from pathlib import Path
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
ctx=get_project_context(sys.argv[1]); signal=Path(sys.argv[2])
def pause(point):
    if point == 'after_registry_reclaim_claim_publish':
        signal.write_text('ready', encoding='utf-8'); time.sleep(30)
s=BranchLifecycleService(ctx, fault_injector=pause); lock=s._lock_path('main')
s._retire_lock_directory(lock, json.loads((lock/'owner.json').read_text(encoding='utf-8')))
"""
    signal = tmp_path / "claimer-ready"
    proc = subprocess.Popen([sys.executable, "-c", child, str(tmp_path), str(signal)], env=_child_env())
    try:
        for _ in range(200):
            if signal.exists():
                break
            time.sleep(0.01)
        assert signal.exists()
        original = json.loads((lock / "reclaim.claim").read_text(encoding="utf-8"))
        with pytest.raises(NarrativeTurnError):
            with _service(tmp_path)._registry_lock("main", timeout=0.08):
                pass
        assert json.loads((lock / "reclaim.claim").read_text(encoding="utf-8")) == original
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_reused_claimant_pid_identity_is_replaced(tmp_path: Path):
    service = _service(tmp_path)
    owner = _released_owner(service)
    lock = _write_lock(service, owner)
    claim = _claim(
        service,
        lock,
        owner,
        pid=os.getpid(),
        process_start_identity="different-process",
    )
    (lock / "reclaim.claim").write_text(json.dumps(claim), encoding="utf-8")
    with service._registry_lock("main", timeout=1):
        pass
    assert not lock.exists()


@pytest.mark.parametrize("mismatch", ["owner_nonce", "owner_fingerprint"])
def test_claim_authority_mismatch_fails_closed(tmp_path: Path, mismatch: str):
    service = _service(tmp_path)
    owner = _released_owner(service)
    lock = _write_lock(service, owner)
    values = {mismatch: "different-authority"}
    claim = _claim(service, lock, owner, **values)
    (lock / "reclaim.claim").write_text(json.dumps(claim), encoding="utf-8")
    with pytest.raises(NarrativeTurnError):
        with service._registry_lock("main", timeout=0.08):
            pass
    assert json.loads((lock / "owner.json").read_text(encoding="utf-8")) == owner
    assert json.loads((lock / "reclaim.claim").read_text(encoding="utf-8")) == claim


def test_two_reclaimers_of_orphan_claim_never_overlap(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _released_owner(service))
    crashing = _spawn_crashing_reclaimer(tmp_path, "after_registry_reclaim_claim_publish")
    assert crashing.wait(timeout=10) == 73
    journal = tmp_path / "critical.log"
    child = """
import os, sys, time
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
s=BranchLifecycleService(get_project_context(sys.argv[1]))
with s._registry_lock('main', timeout=3):
    with open(sys.argv[2], 'a', encoding='utf-8') as h: h.write('enter '+str(os.getpid())+'\\n')
    time.sleep(.05)
    with open(sys.argv[2], 'a', encoding='utf-8') as h: h.write('exit '+str(os.getpid())+'\\n')
"""
    processes = [
        subprocess.Popen([sys.executable, "-c", child, str(tmp_path), str(journal)], env=_child_env())
        for _ in range(2)
    ]
    assert [proc.wait(timeout=10) for proc in processes] == [0, 0]
    active: set[str] = set()
    maximum = 0
    for line in journal.read_text(encoding="utf-8").splitlines():
        action, pid = line.split()
        if action == "enter":
            active.add(pid)
            maximum = max(maximum, len(active))
        else:
            active.remove(pid)
    assert maximum == 1
    assert not lock.exists()


def test_consecutive_orphan_claimers_eventually_recover(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _released_owner(service))
    for _ in range(2):
        proc = _spawn_crashing_reclaimer(tmp_path, "after_registry_reclaim_claim_publish")
        assert proc.wait(timeout=10) == 73
        assert lock.exists()
    with service._registry_lock("main", timeout=1):
        pass
    assert not lock.exists()


@pytest.mark.parametrize("contents", ["not-json", json.dumps({"pid": 1})])
def test_corrupt_or_incomplete_reclaim_claim_fails_closed(tmp_path: Path, contents: str):
    service = _service(tmp_path)
    owner = _released_owner(service)
    lock = _write_lock(service, owner)
    (lock / "reclaim.claim").write_text(contents, encoding="utf-8")
    with pytest.raises(NarrativeTurnError):
        with service._registry_lock("main", timeout=0.08):
            pass
    assert lock.exists()


def test_death_after_handoff_does_not_block_successor(tmp_path: Path):
    service = _service(tmp_path)
    lock = _write_lock(service, _released_owner(service))
    proc = _spawn_crashing_reclaimer(tmp_path, "after_registry_reclaim_handoff")
    assert proc.wait(timeout=10) == 73
    assert not lock.exists()
    with service._registry_lock("main", timeout=1):
        pass


def test_orphan_claims_are_isolated_by_timeline(tmp_path: Path):
    service = _service(tmp_path)
    main_owner = _released_owner(service, "main-owner")
    main_lock = _write_lock(service, main_owner)
    (main_lock / "reclaim.claim").write_text("not-json", encoding="utf-8")
    with service._registry_lock("other", timeout=0.2):
        pass
    assert main_lock.exists()


def test_old_claimer_cannot_retire_successor_authority(tmp_path: Path):
    service = _service(tmp_path)
    old_owner = _released_owner(service, "old-owner")
    lock = _write_lock(service, old_owner)
    assert service._retire_lock_directory(lock, old_owner) is True
    successor = _owner(service, nonce="successor", state="held")
    _write_lock(service, successor)
    assert service._retire_lock_directory(lock, old_owner) is False
    assert json.loads((lock / "owner.json").read_text(encoding="utf-8")) == successor
