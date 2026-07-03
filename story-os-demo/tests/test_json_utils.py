from __future__ import annotations

from llm.json_utils import deep_merge_missing, ensure_required_keys, extract_json_from_text


def test_extract_json_from_plain_text() -> None:
    assert extract_json_from_text('{"title": "A"}') == {"title": "A"}


def test_extract_json_from_fenced_block() -> None:
    text = '```json\n{"title": "A", "count": 1}\n```'
    assert extract_json_from_text(text) == {"title": "A", "count": 1}


def test_extract_json_from_embedded_text() -> None:
    text = 'before {"title": "A"} after'
    assert extract_json_from_text(text) == {"title": "A"}


def test_extract_json_from_invalid_text_returns_empty_dict() -> None:
    assert extract_json_from_text("not json") == {}


def test_ensure_required_keys_returns_missing_keys() -> None:
    assert ensure_required_keys({"a": 1}, ["a", "b"]) == ["b"]


def test_deep_merge_missing_keeps_patch_and_fills_missing_nested_values() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "empty": "fallback"}
    patch = {"a": 9, "nested": {"x": 7}, "empty": ""}

    assert deep_merge_missing(base, patch) == {
        "a": 9,
        "nested": {"x": 7, "y": 2},
        "empty": "fallback",
    }
