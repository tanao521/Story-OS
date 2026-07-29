from __future__ import annotations

import pytest
from core.project_context import get_project_context
from system.narrative_chapter_compiler import CompilationScope, NarrativeCompilationError


def test_phase0d4f_scope_requires_explicit_source_and_branch(tmp_path):
    context = get_project_context(tmp_path)
    scope = CompilationScope(context.root.name, "", "", 1, None, None, "canon", "registry")
    with pytest.raises(NarrativeCompilationError) as exc:
        scope.validate(context)
    assert exc.value.code == "COMPILATION_SCOPE_REQUIRED"


def test_phase0d4f_scope_accepts_fingerprint_source(tmp_path):
    context = get_project_context(tmp_path)
    scope = CompilationScope(context.root.name, "timeline", "branch", 1, None, "a" * 64, "canon", "registry")
    scope.validate(context)
