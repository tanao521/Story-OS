from pathlib import Path

from agents.workflow import WorkflowEngine
from core.project_context import get_project_context


def test_creative_team_contract_is_present():
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web" / "routes.py").read_text(encoding="utf-8")
    markup = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "creative-team.js").read_text(encoding="utf-8")
    for token in ("/api/agents", "/api/workflows", "/api/creative/reviews", "/api/creative/debate", "/api/reader/simulate", "/api/character/simulate"):
        assert token in routes
    for token in ("creative-team-panel", "creative-team-roster", "creative-meeting-record", "creative-team-reader", "creative-team-character"):
        assert token in markup
    assert "/api/workflows/run" in script and "/api/creative/debate" in script and "waiting_for_human" in script
    assert "meetingResults" in script and "model_advisory_error" in script


def test_checkpoint_shows_its_proposal_before_author_confirmation(tmp_path):
    context = get_project_context(tmp_path)
    engine = WorkflowEngine(context)
    engine.executor.execute = lambda agent_id, snapshot, **kwargs: {"trace_id": f"trace-{agent_id}", "result": {"creative_brief": "Keep the protagonist under immediate pressure.", "human_checkpoint": "Confirm this brief."}}
    run = engine.start("chapter_creative_v1", {"context_ref": "test"})
    first = run["steps"][0]
    assert run["status"] == "waiting_for_human"
    assert first["status"] == "waiting_for_human"
    assert first["result"]["creative_brief"]
    resumed = engine.resume(run["run_id"], {"direct": True})
    assert resumed["steps"][0]["status"] == "completed"
    assert resumed["steps"][1]["status"] == "waiting_for_human"
    assert resumed["steps"][1]["result"]


def test_default_creative_brief_is_chinese(tmp_path):
    context = get_project_context(tmp_path)
    run = WorkflowEngine(context).start("chapter_creative_v1", {"context_ref": "test"})
    proposal = run["steps"][0]["result"]
    assert proposal["creative_brief"] == "推动本章发展，并让主角面对清晰且会改变局面的后果。"
    assert proposal["decision"] == "让本章始终兑现当前故事已经建立的核心承诺。"
    assert proposal["human_checkpoint"] == "请确认这份创作简报，再进入后续的情节设计。"
