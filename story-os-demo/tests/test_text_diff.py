from __future__ import annotations

from system.text_diff import build_text_diff, split_text_for_diff


def test_split_text_for_diff_splits_paragraphs() -> None:
    result = split_text_for_diff("第一段。\n\n第二段。")

    assert result == ["第一段。", "第二段。"]


def test_split_text_for_diff_splits_long_paragraph() -> None:
    text = "这是很长的一句。" * 40

    result = split_text_for_diff(text)

    assert len(result) > 1


def test_build_text_diff_returns_summary() -> None:
    result = build_text_diff("旧段落。", "新段落。")

    assert "summary" in result
    assert result["summary"]["left_chars"] == 4


def test_build_text_diff_detects_added() -> None:
    result = build_text_diff("相同。", "相同。\n\n新增。")

    assert any(line["type"] == "added" for line in result["diff_lines"])


def test_build_text_diff_detects_removed() -> None:
    result = build_text_diff("相同。\n\n删除。", "相同。")

    assert any(line["type"] == "removed" for line in result["diff_lines"])


def test_diff_html_escapes_html() -> None:
    result = build_text_diff("<script>alert(1)</script>", "安全文本")

    assert "<script>" not in result["diff_html"]
    assert "&lt;script&gt;" in result["diff_html"]


def test_changed_ratio_between_zero_and_one() -> None:
    result = build_text_diff("旧文本。", "新文本。")

    assert 0 <= result["summary"]["changed_ratio"] <= 1
