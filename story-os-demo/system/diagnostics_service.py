"""Sanitized support report assembled entirely from local health data."""
from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.app_logging import recent_logs
from system.health_checker import HealthChecker
from system.job_manager import get_job_manager


class DiagnosticsService:
    def __init__(self, context:ProjectContext|None=None)->None:self.context=context or get_project_context()
    def snapshot(self)->dict[str,Any]:
        health=HealthChecker(self.context).check()
        return {"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"version":"2.2","environment":{"python":platform.python_version(),"platform":platform.platform()},"health":health,"jobs":get_job_manager().list_jobs(context=self.context,limit=50),"logs":recent_logs(self.context,limit=100)}
    def export(self)->dict[str,Any]:
        report=self.snapshot(); path=self.context.logs_dir/"story_os_diagnostic_report.json"
        from system.data_store import DataStore; DataStore(self.context).write_json(path,report,backup=True)
        return {"path":self.context.relative_path(path),"report":report}
