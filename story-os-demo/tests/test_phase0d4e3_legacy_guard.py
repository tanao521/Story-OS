from pathlib import Path


def test_production_callers_do_not_use_legacy_vector_memory():
    root=Path(__file__).resolve().parents[1]
    files=[
        "system/memory_repair_service.py",
        "system/context_builder.py",
        "system/context_assembly_service.py",
        "system/story_qa.py",
        "system/memory_health.py",
        "system/status_dashboard.py",
        "system/project_clone_service.py",
        "system/job_handlers.py",
        "web/routes.py",
        "commands.py",
    ]
    content="\n".join((root/name).read_text(encoding="utf-8") for name in files)
    assert "from system.vector_memory" not in content
    vector_callers="\n".join(
        (root/name).read_text(encoding="utf-8")
        for name in files
        if name != "system/project_clone_service.py"
    )
    assert "timeline_id=\"main\"" not in vector_callers
    clone=(root/"system/project_clone_service.py").read_text(encoding="utf-8")
    assert "rebuild_project_index(" not in clone


def test_persistent_client_has_one_approved_owner():
    root=Path(__file__).resolve().parents[1]
    matches=[]
    for path in (root/"system").glob("*.py"):
        if "PersistentClient(" in path.read_text(encoding="utf-8"):
            matches.append(path.name)
    assert set(matches) <= {"vector_client_manager.py","vector_memory.py"}
