from __future__ import annotations

from pathlib import Path
from typing import Any

from system.quality_checker import (
    build_quality_report,
    count_chinese_chars,
    detect_ai_style_patterns,
    evaluate_text_by_rules,
    extract_dialogue_lines,
    render_quality_report_markdown,
    save_quality_report,
)


def make_plan() -> dict[str, Any]:
    return {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "chapter_goal": "找到避难所入口",
        "pacing_design": {"ending_hook": "门后传来第二个人的呼吸声"},
        "required_context": {"characters_to_use": [{"name": "林声"}], "world_rules_to_use": []},
    }


def make_text() -> str:
    return (
        "林声沿着墙根往前走，灰尘贴在掌心。他要找到避难所入口，否则水会在天黑前耗尽。\n\n"
        "门边传来轻响，他停住脚步，听见管道里有细小的震动。\n\n"
        "“别说话，先听。”林声压低声音。\n\n"
        "他推开半扇铁门，门后传来第二个人的呼吸声。"
    )


def test_count_chinese_chars_counts_cjk() -> None:
    assert count_chinese_chars("abc中文12") == 2


def test_detect_ai_style_patterns_detects_not_but() -> None:
    result = detect_ai_style_patterns("这不是失败，而是新的开始。")

    assert result["not_but_count"] == 1


def test_detect_ai_style_patterns_detects_dashes() -> None:
    result = detect_ai_style_patterns("他停住——又后退——再抬头。")

    assert result["dash_count"] >= 2


def test_detect_ai_style_patterns_detects_summary_words() -> None:
    result = detect_ai_style_patterns("显然，总之，可以看出这里有问题。")

    assert {"显然", "总之", "可以看出"}.issubset(set(result["summary_words"]))


def test_extract_dialogue_lines_extracts_chinese_quotes() -> None:
    assert extract_dialogue_lines("他说：“先别动。”然后退后。") == ["先别动。"]


def test_evaluate_text_by_rules_returns_scores() -> None:
    result = evaluate_text_by_rules(make_text(), make_plan(), {}, {}, {}, {})

    assert "scores" in result
    assert "story_goal_alignment" in result["scores"]


def test_overall_score_is_between_zero_and_one() -> None:
    result = evaluate_text_by_rules(make_text(), make_plan(), {}, {}, {}, {})

    assert 0 <= result["overall_score"] <= 1


def test_build_quality_report_returns_version() -> None:
    report = build_quality_report(
        {"chapter_id": 1, "chapter_title": "Opening", "edited_text": make_text()},
        "edited",
        1,
        "data/edited/chapter_001_edited_v001.json",
        make_plan(),
        {},
        {},
        {},
        {},
    )

    assert report["quality_version"] == "1.6"


def test_render_quality_report_markdown_contains_title() -> None:
    report = build_quality_report(
        {"chapter_id": 1, "chapter_title": "Opening", "draft_text": make_text()},
        "draft",
        1,
        "data/drafts/chapter_001_draft_v001.json",
        make_plan(),
        {},
        {},
        {},
        {},
    )

    assert "# 第" in render_quality_report_markdown(report)


def test_save_quality_report_writes_json_and_markdown(tmp_path: Path) -> None:
    report = build_quality_report(
        {"chapter_id": 1, "chapter_title": "Opening", "draft_text": make_text()},
        "draft",
        1,
        "data/drafts/chapter_001_draft_v001.json",
        make_plan(),
        {},
        {},
        {},
        {},
    )

    json_path, markdown_path = save_quality_report(report, tmp_path)

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()
