from __future__ import annotations

from core.project_context import get_project_context
from creative_loop.integration import CreativeLoop
from system.data_store import DataStore
from system.job_manager import JobManager
import time


def _context(tmp_path):
    context = get_project_context(tmp_path)
    store = DataStore(context)
    store.write_markdown("data/chapters/chapter_001.md", "林舟在雨夜发现旧钥匙，却必须在救人和保守秘密之间做出选择。")
    store.write_json("data/next_chapter_plan.json", {"chapter_id": 1, "goal": "推动钥匙谜团并迫使主角选择", "planning_version_id": "plan-v1"})
    return context, store


def test_reflection_health_and_issues_bind_active_canon(tmp_path):
    context, _ = _context(tmp_path)
    result = CreativeLoop(context).reflect_chapter(1)
    assert result["reflection"]["canon_version_id"]
    assert result["reflection"]["planning_version_id"] == "plan-v1"
    assert result["health"]["chapter_id"] == 1
    assert result["health"]["dimensions"]["author_style_alignment"] is None
    assert result["health"]["data_quality"]["available_dimensions"] < result["health"]["data_quality"]["total_dimensions"]


def test_proposal_needs_author_decision_and_does_not_change_plan(tmp_path):
    context, store = _context(tmp_path)
    loop = CreativeLoop(context)
    result = loop.reflect_chapter(1)
    issue_ids = [item["issue_id"] for item in loop.issues.list()]
    proposal = loop.proposals.create(issue_ids=issue_ids, reflection_ids=[result["reflection"]["reflection_id"]], health_ids=[result["health"]["health_id"]])
    before = store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict)
    decided = loop.proposals.decide(proposal["proposal_id"], "partially_accepted", accepted_changes=proposal["recommended_changes"][:1], note="只采用第一项")
    assert decided["status"] == "partially_accepted"
    assert store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) == before


def test_experiment_selection_never_rewrites_canon(tmp_path):
    context, store = _context(tmp_path)
    loop = CreativeLoop(context)
    reflection = loop.reflect_chapter(1)["reflection"]
    before = store.read_markdown("data/chapters/chapter_001.md", strict=True)
    experiment = loop.experiments.create({"goal": "比较开场冲突", "source_chapter_id": 1, "source_canon_version_id": reflection["canon_version_id"]})
    experiment = loop.experiments.generate_variants(experiment["experiment_id"], 2)
    experiment = loop.experiments.evaluate(experiment["experiment_id"])
    selected = loop.experiments.select(experiment["experiment_id"], experiment["variants"][1]["variant_id"])
    assert selected["status"] == "selected"
    assert store.read_markdown("data/chapters/chapter_001.md", strict=True) == before


def test_pattern_enters_author_memory_only_after_confirmation(tmp_path):
    context, _ = _context(tmp_path)
    loop = CreativeLoop(context)
    pattern = loop.patterns.propose("failure", [{"chapter": 1}, {"chapter": 2}], "冲突出现过晚", ["开篇"])
    pending = loop.patterns.list()[0]
    assert pending["status"] == "pending_confirmation"
    confirmed = loop.patterns.decide(pattern["pattern_id"], True, "下一卷开篇提前建立冲突")
    assert confirmed["status"] == "confirmed"
    assert confirmed["author_memory_experience_id"]


def test_strategy_outcome_is_correlational_and_handles_missing_data(tmp_path):
    context, _ = _context(tmp_path)
    loop = CreativeLoop(context)
    result = loop.reflect_chapter(1)
    proposal = loop.proposals.create(issue_ids=[], reflection_ids=[result["reflection"]["reflection_id"]], health_ids=[result["health"]["health_id"]])
    loop.proposals.decide(proposal["proposal_id"], "accepted", note="作者决定后续采用")
    proposal = loop.proposals.get(proposal["proposal_id"])
    outcome = loop.outcomes.evaluate(proposal, 4)
    assert outcome["status"] == "insufficient_data"
    assert "相关性" in outcome["conclusion"] or "缺少" in outcome["conclusion"]


def test_chapter_reflection_job_is_bound_to_its_project(tmp_path):
    context, _ = _context(tmp_path)
    manager = JobManager(max_workers=1)
    manager.startup()
    try:
        job = manager.create_job("chapter_reflection", {"chapter_id": 1}, context=context)
        deadline = time.monotonic() + 3
        current = manager.get_job(job["job_id"], context=context)
        while current["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(.02)
            current = manager.get_job(job["job_id"], context=context)
        assert current["project_id"] == context.root.name
        assert current["created_by"] == "user"
        assert "source_version" in current
        assert current["status"] == "completed"
    finally:
        manager.shutdown()


def test_creative_loop_status_machine_audit_and_cache(tmp_path):
    context, _ = _context(tmp_path)
    loop = CreativeLoop(context)
    first = loop.reflect_chapter(1)
    again = loop.reflect_chapter(1)
    assert again["reflection"]["reflection_id"] == first["reflection"]["reflection_id"]
    assert first["reflection"]["status"] == "completed"
    assert [x["new_status"] for x in first["reflection"]["status_history"]] == ["running", "completed"]
    experiment = loop.experiments.create({"goal": "隔离测试"})
    try:
        loop.experiments.select(experiment["experiment_id"], "missing")
        assert False, "draft experiment must not be selectable"
    except RuntimeError as exc:
        assert "NOT_SELECTABLE" in str(exc)
    assert list(context.creative_events_dir.glob("*.json"))
    assert list(context.creative_audit_dir.glob("*.json"))


def test_health_reports_sources_missing_dimensions_and_standard_cost_profile(tmp_path):
    context, _ = _context(tmp_path)
    result = CreativeLoop(context).reflect_chapter(1)
    health = result["health"]
    assert health["available_dimensions"] == health["data_quality"]["available_dimensions"]
    assert "author_style_alignment" in health["missing_dimensions"]
    assert health["dimension_details"]["plot_momentum"]["source"]
    assert result["critic"] is None


def test_experiment_never_enters_story_memory_or_vector_index(tmp_path):
    context, store = _context(tmp_path)
    loop = CreativeLoop(context)
    experiment = loop.experiments.create({"goal": "隔离候选"})
    generated = loop.experiments.generate_variants(experiment["experiment_id"])
    candidate = generated["variants"][0]["content"]
    assert candidate not in store.read_markdown("data/chapters/chapter_001.md", strict=True)
    assert not context.memory_dir.exists() or candidate not in str(list(context.memory_dir.rglob("*")))
    assert not (context.data_dir / "chroma").exists()


def test_creative_loop_data_is_project_scoped(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, second = get_project_context(tmp_path / "a"), get_project_context(tmp_path / "b")
    DataStore(first).write_markdown("data/chapters/chapter_001.md", "第一项目的冲突。")
    DataStore(first).write_json("data/next_chapter_plan.json", {"chapter_id": 1})
    CreativeLoop(first).reflect_chapter(1)
    assert CreativeLoop(first).reflections.list()
    assert CreativeLoop(second).reflections.list() == []
