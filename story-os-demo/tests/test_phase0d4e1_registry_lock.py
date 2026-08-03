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
