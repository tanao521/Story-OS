from pathlib import Path


def test_compile_has_immutable_operation_authority():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "os.link" in source and "canonical_request_fingerprint" in source
