from pathlib import Path


def test_turn_records_are_not_mutated_by_compiler():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "append_transition" in source
    assert "included_in_chapter" not in source.lower() or "Turn records" in source
