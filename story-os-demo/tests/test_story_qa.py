from __future__ import annotations

import json
from pathlib import Path

import pytest

from system.story_qa import (
    answer_from_memory,
    answer_from_state,
    answer_from_story,
    load_story_sources,
    normalize_question,
    save_qa_log,
    search_memory_summaries,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_sources(root: Path) -> None:
    write_json(root / "data" / "state.json", {
        "current_chapter": 2,
        "foreshadows": [
            {"id": "fs_001", "content": "地下室铁门敲击声", "status": "open"},
            {"id": "fs_002", "content": "旧录音笔", "status": "resolved"},
        ],
        "characters": {
            "林北": {
                "physical": "轻伤",
                "mental": "警惕",
                "known_information": ["避难所广播不可信"],
            }
        },
    })
    write_json(root / "data" / "characters.json", {
        "main_characters": [
            {
                "id": "char_001",
                "name": "苏星野",
                "role": "主角",
                "current_state": {"physical": "疲惫"},
                "relationships": {},
                "voice_profile": {"tone": "克制"},
            }
        ],
        "supporting_characters": [],
    })
    write_json(root / "data" / "world_bible.json", {"core_rules": [{"rule": "避难所需要贡献点换取物资"}]})
    write_json(root / "data" / "todos" / "todos.json", {"todo_version": "1.8", "next_id": 1, "items": []})
    write_json(root / "data" / "summaries" / "chapter_002_summary.json", {
        "chapter_id": 2,
        "chapter_title": "地下室",
        "short_summary": "林北第一次听见地下室铁门敲击声。",
        "key_events": ["钱满仓提到线下招商会和传销组织"],
        "memory_tags": ["铁门", "钱满仓"],
    })


def test_normalize_question_strips_and_lowers() -> None:
    assert normalize_question("  WHAT happened  ") == "what happened"


def test_normalize_question_rejects_empty() -> None:
    with pytest.raises(ValueError):
        normalize_question("   ")


def test_load_story_sources_missing_files_does_not_crash(tmp_path: Path) -> None:
    sources = load_story_sources(tmp_path / "data")

    assert sources["state"] == {}
    assert sources["_meta"]["warnings"]


def test_answer_from_state_answers_current_chapter(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    result = answer_from_state("现在第几章了？", tmp_path / "data")

    assert result["confidence"] == "high"
    assert "第 2 章" in result["answer"]


def test_answer_from_state_answers_open_foreshadows(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    result = answer_from_state("现在还有哪些 open 伏笔？", tmp_path / "data")

    assert "地下室铁门敲击声" in result["answer"]


def test_answer_from_state_answers_character_status(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    result = answer_from_state("林北当前状态是什么？", tmp_path / "data")

    assert "轻伤" in result["answer"]


def test_search_memory_summaries_hits_key_events(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    results = search_memory_summaries("钱满仓什么时候提到传销组织？", tmp_path / "data")

    assert results
    assert results[0]["chapter_id"] == 2


def test_answer_from_memory_unknown_when_no_results(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    result = answer_from_memory("完全不存在的问题", tmp_path / "data", use_vector=False)

    assert result["confidence"] == "unknown"


def test_answer_from_story_combines_state_and_memory(tmp_path: Path) -> None:
    prepare_sources(tmp_path)

    result = answer_from_story("林北当前状态以及铁门敲击声出现在哪里？", tmp_path / "data", use_vector=False)

    assert result["confidence"] in {"high", "medium"}
    assert "林北" in result["answer"]
    assert result["sources"]


def test_save_qa_log_writes_json_and_markdown(tmp_path: Path) -> None:
    result = answer_from_state("现在第几章了？", tmp_path / "data")

    json_path, markdown_path = save_qa_log(result, tmp_path / "data")

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()
