from __future__ import annotations

from typing import Any, Callable

import commands
from core.project_context import ProjectContext
from system.pipeline_runner import run_single_chapter_pipeline

Emit = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]

STEP_LABELS = {
    "build-context": "Build writing context",
    "plan-next": "Plan next chapter",
    "write-draft": "Write draft",
    "prepare-review": "Prepare review",
    "index-vault": "Update vector index",
    "sync-obsidian": "Sync Obsidian",
    "quality-check": "Quality assessment",
    "continuity-check": "Continuity check",
    "memory-health": "Memory health check",
    "revision-quality": "Check revision quality", "revision-continuity": "Check revision continuity",
    "revision-impact": "Analyze revision impact", "apply-revision": "Apply approved revision",
    "restore-canon": "Restore historical canon", "rebuild-summary": "Rebuild chapter summary",
    "reindex-chapter": "Reindex chapter memory", "sync-revised-chapter": "Sync revised chapter",
    "chapter-reflection": "Reflect active canon chapter", "full-creative-review": "Run full creative review",
    "creative-proposal": "Generate strategy proposal", "experiment-variants": "Generate experiment variants",
    "evaluate-experiment": "Evaluate creative experiment",
    "generate-quality-report": "\u751f\u6210\u5f53\u524d\u6b63\u53f2\u8d28\u91cf\u62a5\u544a",
    "initialize-vector-index": "\u521d\u59cb\u5316\u672c\u5730\u5411\u91cf\u7d22\u5f15",
    "incremental-vector-index": "\u66f4\u65b0\u672c\u5730\u5411\u91cf\u7d22\u5f15",
    "rebuild-vector-index": "\u91cd\u5efa\u672c\u5730\u5411\u91cf\u7d22\u5f15",
}


def run_job(job: dict[str, Any], context: ProjectContext, emit: Emit,
            cancellation_requested: CancelCheck) -> dict[str, Any]:
    from llm.model_gateway import bind_model_route_snapshot
    with bind_model_route_snapshot(dict(job.get("parameters") or {}).get("model_routing")):
        return _run_job_bound(job, context, emit, cancellation_requested)


def _run_job_bound(job: dict[str, Any], context: ProjectContext, emit: Emit,
                   cancellation_requested: CancelCheck) -> dict[str, Any]:
    job_type = job["job_type"]
    if job_type == "run_chapter":
        report = run_single_chapter_pipeline(
            auto_commit=False,
            require_model=True,
            context=context,
            progress_callback=emit,
            cancellation_token=cancellation_requested,
        )
        return {"pipeline_report": report, "chapter_id": report.get("chapter_id")}
    if job_type == "index_vault":
        return _run_command("index-vault", commands.index_vault_command, emit, cancellation_requested)
    if job_type == "sync_obsidian":
        return _run_command("sync-obsidian", commands.sync_obsidian_command, emit, cancellation_requested)
    if job_type == "quality_check":
        return _run_command("quality-check", commands.quality_check_command, emit, cancellation_requested)
    if job_type == "memory_health":
        return _run_command("memory-health", commands.memory_health_command, emit, cancellation_requested)
    if job_type == "generate_quality_report":
        from system.memory_repair_service import MemoryRepairService
        from system.revision_service import RevisionService
        params = dict(job.get("parameters") or {})
        name = "generate-quality-report"
        emit({"name": name, "label": STEP_LABELS[name], "status": "running"})
        if cancellation_requested():
            return {"cancelled": True}
        active = RevisionService(context).active_canon(int(params["chapter_id"]))
        if active["canon_version_id"] != params.get("canon_version_id") or active["content_hash"] != params.get("content_hash"):
            return {"status": "superseded", "message": "\u6b63\u53f2\u7248\u672c\u5df2\u53d8\u5316\uff0c\u672a\u5199\u5165\u8fc7\u65f6\u8d28\u91cf\u62a5\u544a\u3002"}
        result = MemoryRepairService(context).build_quality_report(int(params["chapter_id"]), force=bool(params.get("force", False)), analysis_profile=str(params.get("analysis_profile") or "lite"))
        emit({"name": name, "label": STEP_LABELS[name], "status": "completed", "outputs": {"chapter_id": int(params["chapter_id"]), "status": result["status"]}})
        return result
    if job_type in {"initialize_vector_index", "incremental_vector_index", "rebuild_vector_index"}:
        from system.memory_repair_service import MemoryRepairService
        name = {"initialize_vector_index": "initialize-vector-index", "incremental_vector_index": "incremental-vector-index", "rebuild_vector_index": "rebuild-vector-index"}[job_type]
        emit({"name": name, "label": STEP_LABELS[name], "status": "running"})
        if cancellation_requested():
            return {"cancelled": True}
        result = MemoryRepairService(context).initialize_vector_index(rebuild=job_type == "rebuild_vector_index", job_id=str(job.get("job_id") or ""))
        if result.get("status") in {"failed", "not_configured"}:
            raise RuntimeError(str(result.get("message") or "Vector index initialization failed."))
        emit({"name": name, "label": STEP_LABELS[name], "status": "completed", "outputs": result.get("outputs", {})})
        return result
    if job_type.startswith("revision_") or job_type in {"apply_revision", "restore_canon_version"}:
        return _run_revision_job(job, context, emit, cancellation_requested)
    if job_type == "reindex_chapter_memory":
        result = _run_command("reindex-chapter", commands.index_vault_command, emit, cancellation_requested)
        if not result.get("cancelled"):
            from system.data_store import DataStore
            from system.revision_service import RevisionService
            chapter = int((job.get("parameters") or {})["chapter_id"]); canon = RevisionService(context).active_canon(chapter); store = DataStore(context)
            state = store.read_json("data/derived_state.json", default={"artifacts": []}, expected_type=dict) or {"artifacts": []}
            for item in state.get("artifacts", []):
                if item.get("artifact_type") == "vector_memory" and item.get("chapter_id") == chapter: item.update({"status":"current","current_canon_version_id":canon["canon_version_id"]})
            store.write_json("data/derived_state.json", state)
        return result
    if job_type == "sync_revised_chapter_to_obsidian":
        return _run_command("sync-revised-chapter", commands.sync_obsidian_command, emit, cancellation_requested)
    if job_type in {"extract_narrative_events", "rebuild_narrative_memory", "recheck_memory_conflicts", "generate_context_preview"}:
        from system.narrative_memory_service import NarrativeMemoryService
        service=NarrativeMemoryService(context); chapter=int((job.get("parameters") or {}).get("chapter_id",1)); name={"extract_narrative_events":"extract-events","rebuild_narrative_memory":"rebuild-narrative","recheck_memory_conflicts":"recheck-conflicts","generate_context_preview":"context-preview"}[job_type]; emit({"name":name,"label":name,"status":"running"}); result=service.extract(chapter) if job_type=="extract_narrative_events" else (service.project() if job_type=="rebuild_narrative_memory" else (service.conflicts() if job_type=="recheck_memory_conflicts" else service.preview(chapter))); emit({"name":name,"label":name,"status":"completed","outputs":{"result":result}}); return {"result":result}
    if job_type == "rebuild_chapter_summary":
        return _rebuild_summary(job, context, emit, cancellation_requested)
    if job_type == "agent_workflow":
        from agents.workflow import WorkflowEngine
        params = dict(job.get("parameters") or {})
        emit({"name": "agent-workflow", "label": "Run creative-team workflow", "status": "running"})
        if cancellation_requested():
            return {"cancelled": True}
        engine = WorkflowEngine(context)
        if params.get("workflow_run_id"):
            run = engine.resume(str(params["workflow_run_id"]), params.get("decisions") if isinstance(params.get("decisions"), dict) else {})
        else:
            run = engine.start(str(params.get("workflow_id", "chapter_creative_v1")), params.get("context_snapshot") if isinstance(params.get("context_snapshot"), dict) else {}, params.get("decisions") if isinstance(params.get("decisions"), dict) else {})
        emit({"name": "agent-workflow", "label": "Run creative-team workflow", "status": "completed", "outputs": {"run_id": run["run_id"], "status": run["status"]}})
        return {"workflow_run": run, "workflow_status": run["status"]}
    if job_type in {"chapter_reflection", "full_creative_review"}:
        from creative_loop.integration import CreativeLoop
        chapter_id = int((job.get("parameters") or {}).get("chapter_id", 0) or 0)
        if chapter_id <= 0:
            raise ValueError("chapter_reflection requires chapter_id")
        name = "chapter-reflection" if job_type == "chapter_reflection" else "full-creative-review"
        emit({"name": name, "label": STEP_LABELS[name], "status": "running"})
        params = dict(job.get("parameters") or {})
        result = CreativeLoop(context).reflect_chapter(chapter_id, force=bool(params.get("force", False)), profile=str(params.get("profile") or ("deep" if job_type == "full_creative_review" else "standard")))
        emit({"name": name, "label": STEP_LABELS[name], "status": "completed", "outputs": {"reflection_id": result["reflection"]["reflection_id"], "health_id": result["health"]["health_id"]}})
        return result
    if job_type == "generate_creative_proposal":
        from creative_loop.integration import CreativeLoop
        emit({"name": "creative-proposal", "label": STEP_LABELS["creative-proposal"], "status": "running"})
        proposal = CreativeLoop(context).proposals.create(**dict(job.get("parameters") or {}))
        emit({"name": "creative-proposal", "label": STEP_LABELS["creative-proposal"], "status": "completed", "outputs": {"proposal_id": proposal["proposal_id"]}})
        return {"proposal": proposal}
    if job_type == "generate_experiment_variants":
        from creative_loop.integration import CreativeLoop
        params = dict(job.get("parameters") or {}); emit({"name": "experiment-variants", "label": STEP_LABELS["experiment-variants"], "status": "running"})
        experiment = CreativeLoop(context).experiments.generate_variants(str(params["experiment_id"]), int(params.get("count", 2)))
        emit({"name": "experiment-variants", "label": STEP_LABELS["experiment-variants"], "status": "completed", "outputs": {"experiment_id": experiment["experiment_id"]}})
        return {"experiment": experiment}
    if job_type == "evaluate_experiment":
        from creative_loop.integration import CreativeLoop
        experiment_id = str((job.get("parameters") or {})["experiment_id"]); emit({"name": "evaluate-experiment", "label": STEP_LABELS["evaluate-experiment"], "status": "running"})
        experiment = CreativeLoop(context).experiments.evaluate(experiment_id)
        emit({"name": "evaluate-experiment", "label": STEP_LABELS["evaluate-experiment"], "status": "completed", "outputs": {"experiment_id": experiment_id}})
        return {"experiment": experiment}
    if job_type == "detect_creative_patterns":
        params = dict(job.get("parameters") or {})
        emit({"name": "detect-creative-patterns", "label": STEP_LABELS["detect-creative-patterns"], "status": "running"})
        pattern = CreativeLoop(context).patterns.propose(str(params.get("kind") or "failure"), params.get("evidence") if isinstance(params.get("evidence"), list) else [], str(params.get("summary") or ""), params.get("conditions") if isinstance(params.get("conditions"), list) else [])
        emit({"name": "detect-creative-patterns", "label": STEP_LABELS["detect-creative-patterns"], "status": "completed", "outputs": {"pattern_id": pattern["pattern_id"]}})
        return {"pattern": pattern}
    if job_type == "evaluate_strategy_outcome":
        params = dict(job.get("parameters") or {})
        loop = CreativeLoop(context); proposal = loop.proposals.get(str(params["proposal_id"]))
        emit({"name": "evaluate-strategy-outcome", "label": STEP_LABELS["evaluate-strategy-outcome"], "status": "running"})
        outcome = loop.outcomes.evaluate(proposal, int(params.get("after_chapter_id") or 0))
        emit({"name": "evaluate-strategy-outcome", "label": STEP_LABELS["evaluate-strategy-outcome"], "status": "completed", "outputs": {"outcome_id": outcome["outcome_id"]}})
        return {"outcome": outcome}
    raise ValueError(f"Unsupported job type: {job_type}")


def _run_command(name: str, command: Callable[[], dict[str, Any]], emit: Emit,
                 cancellation_requested: CancelCheck) -> dict[str, Any]:
    if cancellation_requested():
        return {"cancelled": True}
    emit({"event": "step", "name": name, "label": STEP_LABELS[name], "status": "running"})
    try:
        output = command()
    except Exception as exc:
        emit({"event": "step", "name": name, "label": STEP_LABELS[name], "status": "failed", "message": str(exc)[:300]})
        raise
    status = str(output.get("status", "success"))
    if status == "failed":
        message = str(output.get("message", "Command failed."))
        emit({"event": "step", "name": name, "label": STEP_LABELS[name], "status": "failed", "message": message[:300]})
        raise RuntimeError(message)
    if cancellation_requested():
        emit({"event": "step", "name": name, "label": STEP_LABELS[name], "status": "completed", "message": output.get("message", "")})
        return {"cancelled": True, "output": output}
    emit({"event": "step", "name": name, "label": STEP_LABELS[name], "status": "completed", "message": output.get("message", ""), "outputs": output.get("outputs", {}), "warnings": output.get("warnings", [])})
    return {"output": output}



def _run_revision_job(job: dict[str, Any], context: ProjectContext, emit: Emit, cancellation_requested: CancelCheck) -> dict[str, Any]:
    from system.revision_service import RevisionService
    if cancellation_requested():
        return {"cancelled": True}
    service = RevisionService(context)
    params = dict(job.get("parameters") or {})
    kind = job["job_type"]
    names = {"revision_quality_check": "revision-quality", "revision_continuity_check": "revision-continuity", "revision_impact_analysis": "revision-impact", "apply_revision": "apply-revision", "restore_canon_version": "restore-canon"}
    name = names[kind]
    emit({"name": name, "label": STEP_LABELS.get(name, name), "status": "running"})
    revision_id = str(params.get("revision_id", ""))
    candidate_id = params.get("candidate_version_id")
    if kind == "revision_quality_check":
        result = service.quality_check(revision_id, candidate_id)
    elif kind == "revision_continuity_check":
        result = service.continuity_check(revision_id, candidate_id)
    elif kind == "revision_impact_analysis":
        result = service.impact_analysis(revision_id, candidate_id)
    elif kind == "apply_revision":
        result = service.apply(revision_id)
    else:
        result = service.restore_canon(int(params["chapter_id"]), str(params["version_id"]), confirmed_risks=bool(params.get("confirmed_risks")))
    if cancellation_requested():
        return {"cancelled": True, "output": result}
    emit({"name": name, "label": STEP_LABELS.get(name, name), "status": "completed", "message": "Revision operation completed.", "outputs": result})
    return result


def _rebuild_summary(job: dict[str, Any], context: ProjectContext, emit: Emit, cancellation_requested: CancelCheck) -> dict[str, Any]:
    from core.chapter_committer import summarize_chapter
    from system.data_store import DataStore
    from system.revision_service import RevisionService
    emit({"name": "rebuild-summary", "label": STEP_LABELS["rebuild-summary"], "status": "running"})
    if cancellation_requested(): return {"cancelled": True}
    chapter = int(dict(job.get("parameters") or {})["chapter_id"]); store = DataStore(context)
    canon = RevisionService(context).active_canon(chapter)
    plan = store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {"chapter_id": chapter}
    summary = summarize_chapter({"chapter_id": chapter, "manual_text": canon["content"]}, plan)
    summary.update({"source_canon_version_id": canon["canon_version_id"], "source_content_hash": canon["content_hash"], "generated_at": canon.get("activated_at")})
    store.write_json(f"data/summaries/chapter_{chapter:03d}_summary.json", summary, backup=True)
    state = store.read_json("data/derived_state.json", default={"artifacts": []}, expected_type=dict) or {"artifacts": []}
    for item in state.get("artifacts", []):
        if item.get("artifact_type") == "chapter_summary" and item.get("chapter_id") == chapter:
            item.update({"status": "current", "current_canon_version_id": canon["canon_version_id"]})
    store.write_json("data/derived_state.json", state)
    emit({"name":"rebuild-summary","label":STEP_LABELS["rebuild-summary"],"status":"completed","message":"Summary rebuilt from current canon."})
    return {"chapter_id": chapter, "canon_version_id": canon["canon_version_id"], "status": "current"}
