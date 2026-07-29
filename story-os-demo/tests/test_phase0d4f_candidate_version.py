from pathlib import Path


def test_candidate_uses_existing_version_writer_facade():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "VersionWriterFacade" in source
    assert "narrative_compilation" in source
