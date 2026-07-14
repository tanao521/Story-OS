"""Scope filtering for already-built writing context.

Agents never resolve files or project paths.  The caller supplies an immutable
context snapshot and this module removes fields the profile is not allowed to
see before an agent receives it.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class MemoryScopeError(PermissionError):
    pass


KNOWN_SCOPES = {"global", "author_global", "character", "chapter", "draft", "secret"}


def scoped_context(context: dict[str, Any], allowed: list[str]) -> dict[str, Any]:
    unknown = set(allowed) - KNOWN_SCOPES
    if unknown:
        raise MemoryScopeError(f"Unknown memory scope: {', '.join(sorted(unknown))}")
    source = deepcopy(context if isinstance(context, dict) else {})
    result: dict[str, Any] = {"context_ref": source.get("context_ref", "")}
    mapping = {
        "global": ("global_memory", "story", "constraints"),
        "author_global": ("author_global",),
        "character": ("characters", "character_state"),
        "chapter": ("chapter", "chapter_plan", "recent_memory", "retrieval_memory", "state_snapshot"),
        "draft": ("draft", "draft_text"),
        "secret": ("secret", "private_notes"),
    }
    for scope in allowed:
        for key in mapping[scope]:
            if key in source:
                result[key] = source[key]
    return result
