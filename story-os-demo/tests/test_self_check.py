from __future__ import annotations

import sys
import types
from pathlib import Path

from system.self_check import run_self_check


def test_run_self_check_returns_standard_dict() -> None:
    report = run_self_check(".")

    assert isinstance(report, dict)
    assert "ok" in report
    assert "summary" in report
    assert "checks" in report


def test_run_self_check_does_not_call_external_services(monkeypatch) -> None:
    import llm.openai_compatible_client as client_module
    import llm.planning_service as planning_service
    import system.obsidian_sync as obsidian_sync

    vector_memory = types.ModuleType("system.vector_memory")

    def forbidden(*args, **kwargs):
        raise AssertionError("external service should not be called")

    vector_memory.build_or_update_index = forbidden
    monkeypatch.setitem(sys.modules, "system.vector_memory", vector_memory)
    monkeypatch.setattr(planning_service, "create_deepseek_client", forbidden)
    monkeypatch.setattr(client_module.OpenAICompatibleClient, "chat_text", forbidden)
    monkeypatch.setattr(obsidian_sync, "sync_to_obsidian", forbidden)

    report = run_self_check(Path("."))

    assert isinstance(report, dict)
    assert "summary" in report
