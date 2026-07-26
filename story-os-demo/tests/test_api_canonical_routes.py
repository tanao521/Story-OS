from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app


def test_evaluation_list_uses_strict_canonical_pagination(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[int] = []

    class EvaluationStub:
        def __init__(self, context) -> None:
            assert context.root == tmp_path

        def list_reports(self, **kwargs):
            calls.append(kwargs["limit"])
            return [{"evaluation_id": "evaluation-1", "created_at": "2026-01-01T00:00:00Z"}]

    monkeypatch.setattr("web.routes.EvaluationService", EvaluationStub)
    with TestClient(app) as client:
        invalid = client.get("/api/evaluations?target_type=chapter_draft&limit=101")
        valid = client.get("/api/evaluations?target_type=chapter_draft")
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "PAGINATION_LIMIT_INVALID"
    assert valid.json()["result"]["limit"] == 20
    assert calls == [20]


def test_context_preview_calls_context_assembly_service_readonly(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict] = []

    class ContextStub:
        def __init__(self, context) -> None:
            assert context.root == tmp_path

        def assemble(self, **kwargs):
            calls.append(kwargs)
            return {"chapter_number": 2, "read_only": True, "source_manifest": {}}

    monkeypatch.setattr("web.routes.ContextAssemblyService", ContextStub)
    with TestClient(app) as client:
        response = client.get("/api/narrative-memory/context-preview?chapter_id=7")
    assert response.status_code == 200
    assert response.json()["result"]["preview"]["context_ref"] == "context:7"
    assert calls and calls[0]["purpose"] == "chapter_drafting"
    assert not list(tmp_path.rglob("*.bak"))
