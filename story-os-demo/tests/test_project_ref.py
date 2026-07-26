from __future__ import annotations

import pytest

from core.contracts import ProjectRef, ProjectRefError, normalize_project_id
from core.project_context import get_project_context


def _context(tmp_path, name: str):
    root = tmp_path / name
    root.mkdir()
    return get_project_context(root)


def test_project_ref_normalizes_safe_identity_and_hides_local_paths(tmp_path) -> None:
    context = _context(tmp_path, "Story-OS")
    ref = ProjectRef.from_context(context)

    assert ref.project_id == "story-os"
    assert normalize_project_id(" Story-OS ") == "story-os"
    assert ref.public_view().as_dict() == {"project_id": "story-os"}
    assert str(ref.project_root) not in ref.public_view().as_dict().values()
    ref.assert_project_id(context.root.as_posix())


def test_project_ref_rejects_empty_cross_project_and_unsafe_paths(tmp_path) -> None:
    first = _context(tmp_path, "first")
    second = _context(tmp_path, "second")
    ref = ProjectRef.from_context(first)

    with pytest.raises(ProjectRefError, match="project_id") as empty:
        normalize_project_id("")
    assert empty.value.code == "PROJECT_REF_INVALID"
    with pytest.raises(ProjectRefError) as mismatch:
        ref.assert_context(second)
    assert mismatch.value.code == "PROJECT_MISMATCH"
    for value, code in [("C:\\outside.json", "TARGET_PATH_ABSOLUTE"), ("../outside.json", "TARGET_PATH_TRAVERSAL"), ("//server/share/x", "TARGET_PATH_ABSOLUTE")]:
        with pytest.raises(ProjectRefError) as error:
            ref.relative_target_path(value)
        assert error.value.code == code


def test_project_ref_rejects_symlink_escape_when_supported(tmp_path) -> None:
    context = _context(tmp_path, "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = context.root / "linked-outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable on this Windows test host.")

    with pytest.raises(ProjectRefError) as error:
        ProjectRef.from_context(context).relative_target_path("linked-outside/escape.json")
    assert error.value.code == "TARGET_PATH_OUTSIDE_PROJECT"
