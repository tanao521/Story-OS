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
}


def run_job(job: dict[str, Any], context: ProjectContext, emit: Emit,
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
