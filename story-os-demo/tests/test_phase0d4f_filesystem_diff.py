from pathlib import Path


def test_compiler_does_not_directly_write_canon_or_chroma():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "index_scoped_records" not in source
    assert "NarrativeMemory" not in source
