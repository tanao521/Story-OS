from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from core.project_context import get_project_context
from system.context_assembly_service import ContextAssemblyError, ContextAssemblyService


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _index(root: Path) -> dict:
    rows = []
    for chapter in range(1, 5):
        chapter_path = root / "data" / "chapters" / f"chapter_{chapter:03d}.md"
        summary_path = root / "data" / "summaries" / f"chapter_{chapter:03d}_summary.json"
        _write(chapter_path, f"chapter {chapter} secret")
        _write(summary_path, json.dumps({"chapter_id": chapter, "short_summary": f"summary {chapter} secret", "memory_tags": ["secret"]}))
        rows.append({"chapter_id": chapter, "chapter_path": chapter_path.as_posix(), "summary_path": summary_path.as_posix(), "title": f"C{chapter}", "short_summary": f"summary {chapter}", "memory_tags": ["secret"]})
    return {"working_context_chapters": 3, "chapters": rows}


def test_assembly_is_readonly_scoped_and_budgeted(tmp_path: Path) -> None:
    _write(tmp_path / "data/state.json", '{"current_chapter":4,"characters":{"A":"stable"}}')
    _write(tmp_path / "data/story_blueprint.json", '{"title":"protected"}')
    before = {path.name: sha256(path.read_bytes()).hexdigest() for path in (tmp_path / "data/state.json", tmp_path / "data/story_blueprint.json")}
    service = ContextAssemblyService(get_project_context(tmp_path), vector_retriever=lambda query, limit: [{"chunk_id": "v-1", "summary": "retrieved secret", "source_path": "D:/outside/chroma"}])
    package = service.assemble(state={"current_chapter": 4, "characters": {"A": "stable"}}, memory_index=_index(tmp_path), query="secret", purpose="continuity_review")

    assert package["project_id"] == tmp_path.name.casefold()
    assert package["read_only"] is True
    assert package["budget"]["recent_chapters"] == 1
    assert len(package["recent_chapters"]) == 1
    assert package["vector_retrieved_memories"] == []
    assert "D:/outside" not in json.dumps(package)
    assert before == {path.name: sha256(path.read_bytes()).hexdigest() for path in (tmp_path / "data/state.json", tmp_path / "data/story_blueprint.json")}
    assert not list(tmp_path.rglob("*.bak"))


def test_assembly_rejects_invalid_profile_and_external_memory_paths(tmp_path: Path) -> None:
    service = ContextAssemblyService(get_project_context(tmp_path))
    external = tmp_path.parent / "other" / "chapter.md"
    _write(external, "must not be read")
    index = {"chapters": [{"chapter_id": 1, "chapter_path": external.as_posix(), "summary_path": external.as_posix()}]}
    package = service.assemble(state={"current_chapter": 1}, memory_index=index)
    assert package["recent_chapters"][0].get("missing") is True
    assert package["recent_chapters"][0]["chapter_path"].startswith("data/.context-unavailable/")
    try:
        service.assemble(state={}, memory_index={}, purpose="untrusted")
    except ContextAssemblyError as error:
        assert error.code == "CONTEXT_PROFILE_INVALID"
    else:
        raise AssertionError("invalid profile was accepted")


def test_assembly_uses_injected_vector_adapter_without_initializing_legacy_vector(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []
    service = ContextAssemblyService(
        get_project_context(tmp_path),
        vector_retriever=lambda query, limit: calls.append((query, limit)) or [
            {"chunk_id": "chunk-1", "summary": "retrieved", "source_path": "D:/outside/index"}
        ],
    )
    package = service.assemble(
        state={"current_chapter": 1}, memory_index=_index(tmp_path), query="needle",
        purpose="chapter_drafting",
    )
    assert calls == [("needle", package["budget"]["vector_results"])]
    assert package["vector_retrieved_memories"] == [{
        "chunk_id": "chunk-1", "summary": "retrieved", "source_path": "", "source_type": "vector_retrieval", "source_id": "chunk-1",
    }]


def test_web_agent_context_uses_assembly_authority(tmp_path: Path, monkeypatch) -> None:
    import web.routes as routes

    calls: list[dict] = []

    class StubAssembly:
        def __init__(self, context) -> None:
            assert context.root == tmp_path

        def assemble(self, **kwargs) -> dict:
            calls.append(kwargs)
            return {"next_chapter_id": 2, "read_only": True}

    monkeypatch.setattr(routes, "ContextAssemblyService", StubAssembly)
    monkeypatch.setattr(routes, "_ctx", lambda: get_project_context(tmp_path))
    snapshot = routes._agent_context(chapter_id=5)
    assert calls == [{
        "state": {}, "memory_index": {}, "query": "", "story_spec": {},
        "characters": {}, "world_bible": {}, "purpose": "chapter_drafting",
    }]
    assert snapshot["context_ref"] == "context:5"
    assert snapshot["read_only"] is True


def test_cli_context_refresh_uses_assembly_authority(tmp_path: Path, monkeypatch) -> None:
    import commands

    _write(tmp_path / "data/memory/memory_index.json", json.dumps(_index(tmp_path)))
    _write(tmp_path / "data/story_spec.json", "{}")
    _write(tmp_path / "data/characters.json", "{}")
    _write(tmp_path / "data/world_bible.json", "{}")
    calls: list[dict] = []

    class StubAssembly:
        def __init__(self, context) -> None:
            assert context.root == tmp_path

        def assemble(self, **kwargs) -> dict:
            calls.append(kwargs)
            return {"next_chapter_id": 3, "read_only": True}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(commands, "ContextAssemblyService", StubAssembly)
    monkeypatch.setattr(commands, "save_current_context", lambda context: ("data/context/current_context.json", "data/context/current_context.md"))
    monkeypatch.setattr(commands, "load_planning", lambda context: {})
    state = {"current_chapter": 2, "foreshadows": [], "plot": {}}
    context, _, _ = commands._refresh_current_context_after_commit(commands._paths(tmp_path), state)
    assert context["read_only"] is True
    assert calls and calls[0]["purpose"] == "chapter_drafting"
    assert calls[0]["memory_index"]["chapters"][0]["chapter_id"] == 1


def test_assembly_deduplicates_and_marks_conflicts() -> None:
    selected, duplicates, conflicts = ContextAssemblyService._deduplicate(
        [{"source_type": "canon_memory", "source_id": "fact-1", "summary": "Canon"}],
        [{"source_type": "summary_memory", "source_id": "fact-1", "summary": "Canon"}],
        [{"source_type": "vector_retrieval", "source_id": "fact-1", "summary": "Contradiction"}],
    )
    assert selected == [{"source_type": "canon_memory", "source_id": "fact-1"}]
    assert len(duplicates) == 1 and len(conflicts) == 1
