"""Prompts deliberately request local, machine-checkable changes only."""
from __future__ import annotations

import json
from typing import Any


def plan_prompt(source: str, issues: list[dict[str, Any]], limits: dict[str, Any]) -> str:
    return """You are a constrained Chinese-fiction copy editor. Return JSON only.
Create local patches for the selected low-risk issues. Do not rewrite the chapter,
change title/end/outcome/facts, add named people/places, or change world settings.
Allowed actions: compress, clarify, smooth_transition, remove_repetition,
tighten_dialogue, strengthen_existing_emotion, improve_readability,
strengthen_existing_hook, add_existing_fact_reminder.
Schema: {\"patches\":[{\"issue_ids\":[...],\"paragraph_start\":1,\"paragraph_end\":1,
\"anchor\":\"exact source excerpt\",\"action\":\"...\",\"instruction\":\"...\"}]}
Budget: """ + json.dumps(limits, ensure_ascii=False) + "\nSelected issues:\n" + json.dumps(issues, ensure_ascii=False) + "\nSource:\n" + source


def revision_prompt(source: str, plan: dict[str, Any], limits: dict[str, Any]) -> str:
    return """You are a constrained Chinese-fiction copy editor. Return JSON only.
For each approved local patch return a replacement for its exact anchor. Preserve all
facts, named entities, title, ending and outcome. Do not add a full rewritten chapter.
Schema: {\"replacements\":[{\"patch_index\":0,\"anchor\":\"exact original\",\"replacement\":\"local replacement\"}]}
Budget: """ + json.dumps(limits, ensure_ascii=False) + "\nPlan:\n" + json.dumps(plan, ensure_ascii=False) + "\nSource:\n" + source
