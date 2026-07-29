from pathlib import Path


def test_review_authority_does_not_add_a_commit_channel_or_candidate_rewrite():
    source = Path("system/narrative_candidate_review_service.py").read_text(encoding="utf-8")
    assert "commit_chapter(" not in source
    assert "create_work_version" not in source
