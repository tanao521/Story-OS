from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.project_context import get_project_context
from evaluation_engine.production_service import EvaluationProductionError, EvaluationProductionService
from llm.run_recorder import RunRecorder
from tests.test_planning_evaluation_service import _ready


def test_usage_aggregation_pagination_and_unavailable_values(tmp_path) -> None:
    context = get_project_context(tmp_path); recorder = RunRecorder(context)
    first = recorder.start(task_type="chapter_quality_plan", model_key="test", provider="mock", model="mock", prompt_id="x", prompt_version="1", prompt_hash="hash", job_id="job-a", chapter_id=7, route_snapshot={})
    recorder.finish(first, status="completed", usage={"prompt_tokens": 11, "completion_tokens": 7}, cost={"amount": 0.12})
    second = recorder.start(task_type="chapter_quality_revision", model_key="test", provider="mock", model="mock", prompt_id="x", prompt_version="1", prompt_hash="hash", job_id="job-b", chapter_id=7, route_snapshot={})
    recorder.finish(second, status="failed", usage={}, cost={}, error="failed")
    service = EvaluationProductionService(context)
    events = service.usage_events(limit=1, chapter_number=7)
    assert len(events["items"]) == 1 and events["next_cursor"]
    summary = service.usage_summary(chapter_number=7)["totals"]
    assert summary["call_count"] == 2 and summary["token_status"] == "unavailable" and summary["cost_status"] == "unavailable"


def test_export_is_safe_and_maintenance_requires_matching_preview(tmp_path) -> None:
    evaluation = _ready(tmp_path).generate({"target_type": "near_planning_window", "operation_id": "export"})[0]
    service = EvaluationProductionService(get_project_context(tmp_path))
    content_type, body = service.export(evaluation["evaluation_id"], "markdown")
    assert content_type.startswith("text/markdown") and "D:/" not in body and "# Evaluation" in body
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    service.store.write_json("data/evaluations/improvements/request-a/previews/old.json", {"expires_at": expired, "created_at": expired})
    preview = service.maintenance_preview()
    assert preview["count"] == 1
    with __import__("pytest").raises(EvaluationProductionError): service.cleanup({"preview_id": "wrong", "expected_item_ids": [], "operation_id": "cleanup-a"})
    request = {"preview_id": preview["preview_id"], "expected_item_ids": [preview["items"][0]["item_id"]], "operation_id": "cleanup-a"}
    result = service.cleanup(request)
    assert result["deleted_item_ids"] and service.maintenance_preview()["count"] == 0
    assert result["audit"]["target_type"] == "maintenance_audit" and "project_root" not in str(result["audit"])
    assert service.cleanup(request)["replayed"]
    with __import__("pytest").raises(EvaluationProductionError, match="operation_id"):
        service.cleanup({"preview_id": service.maintenance_preview()["preview_id"], "expected_item_ids": [], "operation_id": "cleanup-a"})


def test_evaluation_health_reports_missing_index_reference(tmp_path) -> None:
    service = EvaluationProductionService(get_project_context(tmp_path))
    service.store.write_json("data/evaluations/index.json", {"reports": [{"evaluation_id": "missing", "path": "data/evaluations/missing.json"}]})
    health = service.health()
    assert health["status"] == "warning" and health["missing_report_references"] == ["missing"]
