"""Focused tests for the deterministic, read-only panel review model."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core.contracts.model_persona_execution import ExecutionMode
from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest
from core.contracts.model_persona_panel_review import (
    PanelReviewStaleness,
    PanelReviewStatus,
    PersonaReviewCard,
    PersonaReviewDisplayStatus,
)
from core.contracts.reader_persona import ReaderPanelRequest
from core.project_context import get_project_context
from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
from system.model_persona_panel_review_service import ModelPersonaPanelReviewService
from system.reader_panel_service import ReaderPanelService
from system.model_persona_execution_service import ProviderRequest, ProviderResponse


def _project(tmp_path: Path):
    root = tmp_path / "review-project"
    for relative in ("data/drafts", "data/edited", "data/manual", "data/versions", "data/summaries", "data/planning"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "data/state.json").write_text(json.dumps({"project_id": "review-project", "timeline_id": "main", "current_chapter": 1}), encoding="utf-8")
    (root / "data/story_spec.json").write_text("{}", encoding="utf-8")
    (root / "data/planning/planning.json").write_text(json.dumps({"chapters": [{"chapter_number": 1, "chapter_goal": "goal", "pacing_design": {}}]}), encoding="utf-8")
    draft = root / "data/drafts/chapter_001_draft_v001.json"
    draft.write_text(json.dumps({"chapter_id": 1, "chapter_title": "One", "draft_text": "Opening tension. A threat appears and the protagonist must choose. PROMPT_CANARY"}), encoding="utf-8")
    (root / "data/versions/chapter_001_versions.json").write_text(json.dumps({"drafts": [{"source_type": "draft", "version": 1, "json_path": str(draft), "chapter_title": "One"}], "edited": [], "manual": [], "selected": {}}), encoding="utf-8")
    return get_project_context(root)


class _Provider:
    provider_id = "review-fake"
    model_id = "review-fake-model"

    def __init__(self, outcomes=None):
        self.calls = 0
        self.outcomes = list(outcomes or [])

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        if self.outcomes and isinstance(self.outcomes[0], Exception):
            raise self.outcomes.pop(0)
        if self.outcomes:
            self.outcomes.pop(0)
        return ProviderResponse(json.dumps({
            "reader_reaction": "Useful response",
            "strengths": [], "concerns": [], "reader_questions": [],
            "optimization_directions": [], "overall_impression": "Fine",
        }), usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


def _authority(ctx):
    return ReaderPanelService(ctx).run_panel(ReaderPanelRequest(
        project_id="review-project", timeline_id="main", chapter_id=1,
        persona_ids=["hook_driven_reader", "character_empathy_reader", "world_logic_reader"],
    ))


def _model_request(mode=ExecutionMode.LIVE, force=False):
    return ModelPersonaPanelExecutionRequest(
        project_id="review-project", timeline_id="main", chapter_id=1,
        persona_ids=["world_logic_reader", "hook_driven_reader", "character_empathy_reader"],
        execution_mode=mode, allow_model_call=mode == ExecutionMode.LIVE,
        max_provider_calls=3, force=force,
    )


def test_ready_review_keeps_authority_order_and_is_read_only(tmp_path: Path):
    ctx = _project(tmp_path)
    _authority(ctx)
    provider = _Provider()
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_model_request())
    before = sorted(path.relative_to(ctx.root).as_posix() for path in ctx.root.rglob("*.json"))
    review = ModelPersonaPanelReviewService(ctx, provider=provider).review(chapter_id=1)
    after = sorted(path.relative_to(ctx.root).as_posix() for path in ctx.root.rglob("*.json"))

    assert review.review_status == PanelReviewStatus.READY
    assert review.selected_panel_execution_id == result.panel_execution_id
    assert [card.persona_id for card in review.persona_reviews] == sorted(result.ordered_persona_ids)
    assert all("engagement_score" in card.authoritative for card in review.persona_reviews)
    assert all("model_feedback" in card.model_supplement for card in review.persona_reviews)
    assert review.execution_summary["actual_provider_call_count"] == 3
    assert review.usage_summary["total_tokens"] == 45
    assert review.selected_run_staleness == PanelReviewStaleness.CURRENT
    assert before == after
    encoded = json.dumps(review.to_dict(), ensure_ascii=False)
    assert "draft_text" not in encoded and "PROMPT_CANARY" not in encoded and "system_prompt" not in encoded and "endpoint" not in encoded

    failing_provider = _Provider([RuntimeError("SECRET_CANARY https://secret.example/absolute/path")])
    failed_result = ModelPersonaPanelExecutionService(ctx, provider=failing_provider).execute(_model_request(force=True))
    failed_review = ModelPersonaPanelReviewService(ctx, provider=failing_provider).review(chapter_id=1, panel_execution_id=failed_result.panel_execution_id)
    failed_encoded = json.dumps(failed_review.to_dict(), ensure_ascii=False)
    assert "SECRET_CANARY" not in failed_encoded and "secret.example" not in failed_encoded and "absolute/path" not in failed_encoded


def test_no_run_and_source_missing_are_stable(tmp_path: Path):
    ctx = _project(tmp_path)
    _authority(ctx)
    not_run = ModelPersonaPanelReviewService(ctx).review(chapter_id=1)
    missing = ModelPersonaPanelReviewService(ctx).review(chapter_id=99)
    assert not_run.review_status == PanelReviewStatus.NOT_RUN
    assert not_run.selected_panel_execution_id is None
    assert all(card.display_status == PersonaReviewDisplayStatus.NOT_RUN for card in not_run.persona_reviews)
    assert missing.review_status == PanelReviewStatus.SOURCE_MISSING
    assert missing.selected_run_staleness == PanelReviewStaleness.SOURCE_MISSING


def test_explicit_stale_run_is_selected_without_refresh_or_provider_call(tmp_path: Path):
    ctx = _project(tmp_path)
    _authority(ctx)
    provider = _Provider()
    result = ModelPersonaPanelExecutionService(ctx, provider=provider).execute(_model_request())
    draft = next((ctx.root / "data/drafts").glob("*.json"))
    payload = json.loads(draft.read_text(encoding="utf-8"))
    payload["draft_text"] += " SOURCE_CHANGE_CANARY"
    draft.write_text(json.dumps(payload), encoding="utf-8")
    before = sorted(path.relative_to(ctx.root).as_posix() for path in ctx.root.rglob("*.json"))
    review = ModelPersonaPanelReviewService(ctx, provider=provider).review(chapter_id=1, panel_execution_id=result.panel_execution_id)
    after = sorted(path.relative_to(ctx.root).as_posix() for path in ctx.root.rglob("*.json"))
    assert review.review_status == PanelReviewStatus.STALE
    assert review.selected_run_staleness == PanelReviewStaleness.STALE
    assert "STALE_MODEL_RESULT" in review.warnings
    assert provider.calls == 3
    assert before == after


def test_default_selection_prefers_current_partial_over_stale_completed(tmp_path: Path):
    ctx = _project(tmp_path)
    _authority(ctx)
    completed_provider = _Provider()
    old = ModelPersonaPanelExecutionService(ctx, provider=completed_provider).execute(_model_request())
    draft = next((ctx.root / "data/drafts").glob("*.json"))
    payload = json.loads(draft.read_text(encoding="utf-8"))
    payload["draft_text"] += " NEXT_SOURCE"
    draft.write_text(json.dumps(payload), encoding="utf-8")
    partial_provider = _Provider([RuntimeError("provider failure")])
    partial = ModelPersonaPanelExecutionService(ctx, provider=partial_provider).execute(_model_request(force=True))
    review = ModelPersonaPanelReviewService(ctx, provider=partial_provider).review(chapter_id=1)
    assert partial.status.value == "partially_completed"
    assert review.selected_panel_execution_id == partial.panel_execution_id
    assert review.selection_reason == "current_partially_completed_run"
    assert review.selected_panel_execution_id != old.panel_execution_id
    assert review.review_status == PanelReviewStatus.PARTIAL


def test_agreement_and_conflict_rules_are_structural_and_unresolved(tmp_path: Path):
    service = ModelPersonaPanelReviewService(_project(tmp_path))
    cards = [
        PersonaReviewCard("a", "A", 0, {"retention_risk": 20, "priority_flags": [{"flag_code": "ISSUE", "persona_severity": "low", "evidence_refs": ["EV-1"]}]}, {"evidence_references": ["EV-1"]}, PersonaReviewDisplayStatus.COMPLETE),
        PersonaReviewCard("b", "B", 1, {"retention_risk": 80, "priority_flags": [{"flag_code": "ISSUE", "persona_severity": "high", "evidence_refs": ["EV-2"]}]}, {"evidence_references": ["EV-1"]}, PersonaReviewDisplayStatus.COMPLETE),
    ]
    agreements = service._agreement_groups(cards)
    conflicts = service._conflict_groups(cards)
    assert any(group["category"] == "issue_code" for group in agreements)
    assert any(group["category"] == "evidence_id" for group in agreements)
    assert {group["conflict_type"] for group in conflicts} == {"severity_conflict", "evidence_conflict", "risk_conflict"}
    assert all(group["resolution_status"] == "unresolved" for group in conflicts)


def test_cli_and_web_review_queries_are_read_only(tmp_path: Path):
    ctx = _project(tmp_path)
    _authority(ctx)
    model = ModelPersonaPanelExecutionService(ctx).execute(_model_request(mode=ExecutionMode.MOCK))
    root = Path(__file__).resolve().parents[1]
    cli = subprocess.run([sys.executable, "main.py", "show-reader-persona-panel-review", "--chapter", "1", "--panel-execution-id", model.panel_execution_id, "--project-root", str(ctx.root), "--json"], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert cli.returncode == 0
    assert json.loads(cli.stdout)["outputs"]["review_status"] == "ready"

    from fastapi.testclient import TestClient
    from web.app import app
    client = TestClient(app)
    response = client.get("/api/reader-persona/model-panel/review", params={"chapter_id": 1, "panel_execution_id": model.panel_execution_id, "project_root": str(ctx.root)})
    assert response.status_code == 200
    assert response.json()["result"]["review_status"] == "ready"
    unknown = client.get("/api/reader-persona/model-panel/runs/missing/review", params={"project_root": str(ctx.root)})
    assert unknown.status_code == 404
