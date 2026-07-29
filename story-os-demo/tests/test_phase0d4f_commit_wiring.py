from pathlib import Path


def test_commit_wiring_has_single_existing_commit_entry():
    source = Path("system/narrative_chapter_compiler.py").read_text(encoding="utf-8")
    assert "ChapterCommitService(self.context).commit_chapter" in source
    assert ".apply(" not in source
