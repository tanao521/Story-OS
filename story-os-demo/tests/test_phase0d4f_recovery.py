from pathlib import Path


def test_compile_and_commit_have_durable_phase_files():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "with_suffix(\".phase.json\")" in source
    assert "commit_operations" in source
