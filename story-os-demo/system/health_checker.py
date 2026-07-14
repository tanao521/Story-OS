"""Local environment, project, model, task and storage health checks."""
from __future__ import annotations

import shutil, sys
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext, get_project_context
from llm.model_gateway import get_model_gateway
from system.data_integrity import DataIntegrityChecker
from system.job_manager import get_job_manager


class HealthChecker:
    def __init__(self, context: ProjectContext | None=None)->None:self.context=context or get_project_context()
    def check(self)->dict[str,Any]:
        checks=[]
        checks.append({"name":"python","status":"ok" if sys.version_info>=(3,10) else "error","message":sys.version.split()[0]})
        free=shutil.disk_usage(self.context.root).free; checks.append({"name":"disk_space","status":"ok" if free>100*1024*1024 else "warning","free_bytes":free})
        try:
            self.context.data_dir.mkdir(parents=True,exist_ok=True); probe=self.context.data_dir/".health_probe"; probe.write_text("ok",encoding="utf-8"); probe.unlink()
            checks.append({"name":"storage_permission","status":"ok"})
        except OSError: checks.append({"name":"storage_permission","status":"error","code":"DATA_PERMISSION_DENIED"})
        integrity=DataIntegrityChecker(self.context).check(); checks.extend(integrity["checks"])
        checks.extend({"name":f"model:{item.get('model_key','')}","status":"ok" if item.get("status")=="configured" else "warning","details":item} for item in get_model_gateway(self.context).health())
        stale=get_job_manager().recover_stale_jobs(context=self.context, dry_run=True); checks.append({"name":"jobs","status":"warning" if stale else "ok","stale_jobs":stale})
        status="unhealthy" if any(item.get("status")=="error" for item in checks) else ("warning" if any(item.get("status")=="warning" for item in checks) else "healthy")
        return {"status":status,"checks":checks,"integrity":integrity}
