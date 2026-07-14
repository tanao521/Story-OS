from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.errors import DataCorruptionError, public_error
from core.project_context import get_project_context
from system.backup_service import BackupService
from system.data_integrity import DataIntegrityChecker
from system.data_store import DataStore
from system.health_checker import HealthChecker
from system.job_manager import JobManager
from system.job_models import make_job


def prepared_context(tmp_path: Path):
    root = tmp_path / "project"; root.mkdir(); context = get_project_context(root); store = DataStore(context)
    store.write_json("data/story_spec.json", {"title": "测试"})
    store.write_json("data/story_blueprint.json", {"schema_version": "1.0"})
    store.write_json("data/characters.json", {})
    store.write_json("data/world_bible.json", {})
    store.write_json("data/state.json", {"current_chapter": 0})
    return context


def test_integrity_finds_corrupt_json_without_rewriting_it(tmp_path: Path) -> None:
    context = prepared_context(tmp_path)
    target = context.data_dir / "characters.json"; target.write_text("{broken", encoding="utf-8")
    report = DataIntegrityChecker(context).check()
    assert any(item.get("code") == "DATA_JSON_INVALID" for item in report["checks"])
    assert target.read_text(encoding="utf-8") == "{broken"


def test_backup_restore_creates_safety_snapshot(tmp_path: Path) -> None:
    context = prepared_context(tmp_path); store = DataStore(context); service = BackupService(context)
    backup = service.create("manual")
    store.write_json("data/story_spec.json", {"title": "changed"})
    restored = service.restore(backup["backup_id"])
    assert store.read_json("data/story_spec.json", default={})["title"] == "测试"
    assert restored["safety_backup_id"] != backup["backup_id"]
    assert len(service.list()) >= 2


def test_stale_job_becomes_retryable(tmp_path: Path) -> None:
    context = prepared_context(tmp_path); manager = JobManager(); manager.startup()
    try:
        job = make_job(project_id="project", project_root=manager._project_root(context), job_type="quality_check")
        job.update({"status": "running", "heartbeat_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()})
        manager._save(context, job)
        assert manager.recover_stale_jobs(context=context, max_age_seconds=1) == [job["job_id"]]
        assert manager.get_job(job["job_id"], context=context)["status"] == "recoverable_failed"
    finally:
        manager.shutdown()


def test_public_error_is_sanitized_shape() -> None:
    payload = public_error(DataCorruptionError("Broken JSON", details={"file": "hidden"}, recoverable=True))
    assert payload["code"] == "DATA_JSON_INVALID"
    assert payload["recoverable"] is True


def test_health_checker_uses_local_checks_only(tmp_path: Path) -> None:
    report = HealthChecker(prepared_context(tmp_path)).check()
    assert report["status"] in {"healthy", "warning", "unhealthy"}
    assert any(item["name"] == "python" for item in report["checks"])
