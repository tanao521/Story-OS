from __future__ import annotations

from pathlib import Path

from core.contracts.narrative_turn import NarrativeScope
from core.project_context import get_project_context
from system.narrative_turn_context import NarrativeTurnContextBinder, _stable_fingerprint
from system.version_manager import list_versions, read_version_payload


def test_successor_turn_context_binds_unindexed_draft_source(tmp_path: Path) -> None:
    from tests._phase0d6c_fv_browser_fixture_server import setup_workspace

    info = setup_workspace(tmp_path)
    project_root = Path(info["project"])
    context = get_project_context(project_root)
    scope = NarrativeScope(project_root.name, "main", "main")

    snapshot = NarrativeTurnContextBinder(context).bind(scope, 2)
    versions = list_versions(2, context.data_dir)
    draft = versions["drafts"][-1]
    payload = read_version_payload(draft)

    assert snapshot.source_version_id == "draft_v001"
    assert snapshot.source_fingerprint == _stable_fingerprint(payload["draft_text"])
