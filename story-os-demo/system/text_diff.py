from __future__ import annotations

import difflib
import html
import re
from typing import Any


MAX_SEGMENT_LENGTH = 180


def split_text_for_diff(text: str) -> list[str]:
    """Split Chinese prose into readable diff units."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    result: list[str] = []
    for paragraph in paragraphs:
        result.extend(_split_long_paragraph(paragraph))
    return result


def build_text_diff(
    left_text: str,
    right_text: str,
    context_lines: int = 2,
) -> dict[str, Any]:
    left_lines = split_text_for_diff(left_text)
    right_lines = split_text_for_diff(right_text)
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    diff_lines: list[dict[str, str]] = []
    added_count = 0
    removed_count = 0

    for group in matcher.get_grouped_opcodes(context_lines):
        if diff_lines:
            diff_lines.append({"type": "equal", "text": "..."})
        for tag, left_start, left_end, right_start, right_end in group:
            if tag == "equal":
                for line in left_lines[left_start:left_end]:
                    diff_lines.append({"type": "equal", "text": line})
            elif tag == "delete":
                for line in left_lines[left_start:left_end]:
                    removed_count += 1
                    diff_lines.append({"type": "removed", "text": line})
            elif tag == "insert":
                for line in right_lines[right_start:right_end]:
                    added_count += 1
                    diff_lines.append({"type": "added", "text": line})
            elif tag == "replace":
                for line in left_lines[left_start:left_end]:
                    removed_count += 1
                    diff_lines.append({"type": "removed", "text": line})
                for line in right_lines[right_start:right_end]:
                    added_count += 1
                    diff_lines.append({"type": "added", "text": line})

    max_units = max(len(left_lines), len(right_lines), 1)
    changed_ratio = min(1.0, (added_count + removed_count) / max_units)
    return {
        "summary": {
            "left_chars": len(left_text),
            "right_chars": len(right_text),
            "added_count": added_count,
            "removed_count": removed_count,
            "changed_ratio": round(changed_ratio, 4),
        },
        "diff_lines": diff_lines,
        "diff_html": render_diff_html(diff_lines),
    }


def render_diff_html(diff_lines: list[dict[str, str]]) -> str:
    rows: list[str] = []
    prefix_map = {"added": "+ ", "removed": "- ", "equal": "  ", "changed": "~ "}
    for line in diff_lines:
        line_type = str(line.get("type", "equal"))
        if line_type not in {"added", "removed", "equal", "changed"}:
            line_type = "equal"
        text = html.escape(str(line.get("text", "")))
        prefix = html.escape(prefix_map.get(line_type, "  "))
        rows.append(f'<div class="diff-line diff-{line_type}">{prefix}{text}</div>')
    return "\n".join(rows)


def _split_long_paragraph(paragraph: str) -> list[str]:
    if len(paragraph) <= MAX_SEGMENT_LENGTH:
        return [paragraph]
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?；;”」』])", paragraph) if part.strip()]
    if not parts:
        return _split_by_size(paragraph)
    result: list[str] = []
    current = ""
    for part in parts:
        candidate = current + part if current else part
        if len(candidate) <= MAX_SEGMENT_LENGTH:
            current = candidate
            continue
        if current:
            result.append(current)
            current = part
        while len(current) > MAX_SEGMENT_LENGTH:
            result.append(current[:MAX_SEGMENT_LENGTH])
            current = current[MAX_SEGMENT_LENGTH:]
    if current:
        result.append(current)
    return result


def _split_by_size(text: str) -> list[str]:
    return [text[index:index + MAX_SEGMENT_LENGTH] for index in range(0, len(text), MAX_SEGMENT_LENGTH)]
