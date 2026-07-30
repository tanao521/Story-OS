"""Isolated real-browser fixture for the 0D7-B review evidence surface."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def setup_workspace(root: Path) -> None:
    project_id = root.name
    _write(root / "data" / "story_spec.json", {"title": "Review evidence fixture", "genre": "test"})
    _write(root / "data" / "next_chapter_plan.json", {"chapter_id": 1, "chapter_title": "Fixture"})
    _write(root / "data" / "state.json", {"current_chapter": 0})
    _write(root / "data" / "manual" / "chapter_001_manual_v001.json", {
        "chapter_id": 1, "chapter_title": "Fixture", "version": 1,
        "version_label": "manual_v001", "manual_text": "Fixture text for exact review evidence.",
    })
    _write(root / "data" / "branches" / "main" / "registry.json", {
        "project_id": project_id, "timeline_id": "main", "active_branch_id": "main", "revision": "1",
    })
    from core.project_context import get_project_context
    from system.chapter_assembly_evidence_service import ChapterAssemblyEvidenceScope, ChapterAssemblyEvidenceService
    context = get_project_context(root)
    ChapterAssemblyEvidenceService(context).generate(ChapterAssemblyEvidenceScope(
        project_id=project_id, timeline_id="main", branch_id="main", chapter_id=1,
        source_version_id="manual_v001",
    ))


def main() -> None:
    import uvicorn

    workspace = Path(tempfile.mkdtemp(prefix="phase0d7b_browser_"))
    setup_workspace(workspace)
    os.chdir(workspace)
    from web.app import app
    port = int(os.environ.get("STORYOS_0D7B_PORT", "7864"))
    print(json.dumps({"workspace": str(workspace), "url": f"http://127.0.0.1:{port}/"}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
