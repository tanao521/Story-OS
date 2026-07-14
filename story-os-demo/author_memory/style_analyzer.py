"""Extract general style signals; it never preserves or imitates source prose."""
from __future__ import annotations

import re
from typing import Any


def analyze_style(text: str) -> dict[str, Any]:
    content = str(text or "").strip(); sentences = [x.strip() for x in re.split(r"[。！？!?]+", content) if x.strip()]
    avg = len(content) / max(1, len(sentences)); quotes = content.count("“") + content.count('"'); paragraphs = max(1, len([x for x in content.splitlines() if x.strip()]))
    return {"style_profile": {"sentence_style": "简洁" if avg < 28 else "舒展" if avg > 55 else "均衡", "dialogue": "高" if quotes / max(1, len(content)) > .035 else "中" if quotes else "低", "description": "高" if any(word in content for word in ("仿佛", "像是", "光影", "空气")) else "中", "emotion": "克制" if not any(word in content for word in ("崩溃", "绝望", "狂喜")) else "强烈", "pace": "快速" if avg < 30 or len(sentences) / paragraphs > 5 else "平稳"}, "metrics": {"characters_analyzed": len(content), "average_sentence_length": round(avg, 1), "dialogue_markers": quotes, "paragraphs": paragraphs}, "source": "rule_based", "disclaimer": "仅保存写作规律，不保存、复刻或上传原文。"}
