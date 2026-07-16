from __future__ import annotations

import json

from system.version_manager import select_version
from system.version_writer_facade import VersionWriterFacade


def test_select_version_uses_writer_facade_and_preserves_pointer_shape(tmp_path, monkeypatch) -> None:
    edited = tmp_path / "edited" / "chapter_001_edited_v001.json"
    edited.parent.mkdir(parents=True)
    edited.write_text(json.dumps({"chapter_id": 1, "version": 1, "version_label": "edited_v001", "edited_text": "edited"}), encoding="utf-8")
    calls = []
    original = VersionWriterFacade.write_versions_index
    def tracked(self, **kwargs):
        calls.append(kwargs["index_path"])
        return original(self, **kwargs)
    monkeypatch.setattr(VersionWriterFacade, "write_versions_index", tracked)
    selected = select_version(1, "edited", 1, tmp_path)
    stored = json.loads((tmp_path / "versions/chapter_001_versions.json").read_text(encoding="utf-8"))
    assert selected["source_type"] == "edited" and selected["version_label"] == "edited_v001"
    assert stored["selected"] == selected
    assert calls == [f"{tmp_path.name}/versions/chapter_001_versions.json"]
