"""Phase 0D6-P temporary fixture probes.

All probes use isolated temporary directories. No real project or real
data/chroma is touched. Each probe records SHA-256 manifest before/after.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.project_context import get_project_context
from system.simulator_loop_state import SimulatorLoopStateService
from system.version_manager import list_versions, get_selected_version
from system.revision_service import RevisionService
from system.planning_service import load_planning


def _sha256_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if not root.exists():
        return manifest
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                manifest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                manifest[str(path.relative_to(root))] = "unreadable"
    return manifest


def _diff_manifest(before: dict[str, str], after: dict[str, str]) -> dict[str, tuple[str, str]]:
    diff: dict[str, tuple[str, str]] = {}
    all_keys = set(before.keys()) | set(after.keys())
    for key in sorted(all_keys):
        b = before.get(key, "<MISSING>")
        a = after.get(key, "<MISSING>")
        if b != a:
            diff[key] = (b, a)
    return diff


def _make_fixture_a(root: Path) -> dict:
    """Fixture A: Next chapter exists.

    Chapter 1 committed, Chapter 2 exists with source version, active branch.
    """
    data = root / "data"
    chapters_dir = data / "chapters"
    versions_dir = data / "versions"
    branches_dir = data / "branches"
    chroma_dir = data / "chroma"
    planning_dir = data / "planning_control"

    for d in (chapters_dir, versions_dir, branches_dir, chroma_dir, planning_dir, data / "state"):
        d.mkdir(parents=True, exist_ok=True)

    (chapters_dir / "chapter_001.md").write_text("# Chapter 1\nCommitted content.", encoding="utf-8")
    (chapters_dir / "chapter_002.md").write_text("# Chapter 2\nExisting content.", encoding="utf-8")

    v1_dir = versions_dir / "chapter_001"
    v1_dir.mkdir(parents=True, exist_ok=True)
    (v1_dir / "manual_v001.md").write_text("# Manual v001\nChapter 1 source.", encoding="utf-8")
    (v1_dir / "chapter_001_versions.json").write_text(
        json.dumps({"selected": {"version_label": "manual_v001", "source_type": "manual", "version": 1}}),
        encoding="utf-8",
    )

    v2_dir = versions_dir / "chapter_002"
    v2_dir.mkdir(parents=True, exist_ok=True)
    (v2_dir / "manual_v001.md").write_text("# Manual v001\nChapter 2 source.", encoding="utf-8")
    (v2_dir / "chapter_002_versions.json").write_text(
        json.dumps({"selected": {"version_label": "manual_v001", "source_type": "manual", "version": 1}}),
        encoding="utf-8",
    )

    state_file = data / "state" / "state.json"
    state_file.write_text(json.dumps({"current_chapter": 1}), encoding="utf-8")

    branch_dir = branches_dir / "main"
    branch_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "active_branch_id": "branch_alpha",
        "registry_revision": "rev-001",
        "branches": {
            "branch_alpha": {
                "branch_id": "branch_alpha",
                "display_name": "Alpha",
                "lifecycle_status": "open",
                "is_active": True,
                "created_at": "2026-01-01T00:00:00Z",
            }
        },
    }
    (branch_dir / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")

    planning = {
        "current_chapter": 1,
        "chapters": [
            {"chapter_number": 1, "title": "Chapter 1", "status": "committed"},
            {"chapter_number": 2, "title": "Chapter 2", "status": "draft"},
        ],
    }
    (planning_dir / "story_planning.json").write_text(json.dumps(planning, indent=2), encoding="utf-8")

    (data / "next_chapter_plan.json").write_text(
        json.dumps({"chapter_id": "plan-ch2", "planning_source": "planning"}, indent=2),
        encoding="utf-8",
    )

    canon_dir = data / "canon_versions" / "chapter_001"
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / "index.json").write_text(
        json.dumps({"canon_version_id": "canon-ch1-v1", "revision_id": "rev-001", "active": True}),
        encoding="utf-8",
    )

    manifest_dir = chroma_dir / "manifests" / "main"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "branch_alpha.json").write_text(
        json.dumps({"vector_ready": True, "branch_lifecycle_status": "open", "canon_revision_id": "rev-001"}),
        encoding="utf-8",
    )

    return {"project_id": root.name, "timeline_id": "main", "branch_id": "branch_alpha", "chapter_id": 2}


def _make_fixture_b(root: Path) -> dict:
    """Fixture B: Next chapter absent.

    Chapter 1 committed, Chapter 2 absent.
    """
    data = root / "data"
    chapters_dir = data / "chapters"
    versions_dir = data / "versions"
    branches_dir = data / "branches"
    chroma_dir = data / "chroma"
    planning_dir = data / "planning_control"

    for d in (chapters_dir, versions_dir, branches_dir, chroma_dir, planning_dir, data / "state"):
        d.mkdir(parents=True, exist_ok=True)

    (chapters_dir / "chapter_001.md").write_text("# Chapter 1\nCommitted content.", encoding="utf-8")

    v1_dir = versions_dir / "chapter_001"
    v1_dir.mkdir(parents=True, exist_ok=True)
    (v1_dir / "manual_v001.md").write_text("# Manual v001\nChapter 1 source.", encoding="utf-8")
    (v1_dir / "chapter_001_versions.json").write_text(
        json.dumps({"selected": {"version_label": "manual_v001", "source_type": "manual", "version": 1}}),
        encoding="utf-8",
    )

    state_file = data / "state" / "state.json"
    state_file.write_text(json.dumps({"current_chapter": 1}), encoding="utf-8")

    branch_dir = branches_dir / "main"
    branch_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "active_branch_id": "branch_alpha",
        "registry_revision": "rev-001",
        "branches": {
            "branch_alpha": {
                "branch_id": "branch_alpha",
                "display_name": "Alpha",
                "lifecycle_status": "open",
                "is_active": True,
            }
        },
    }
    (branch_dir / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")

    planning = {
        "current_chapter": 1,
        "chapters": [
            {"chapter_number": 1, "title": "Chapter 1", "status": "committed"},
        ],
    }
    (planning_dir / "story_planning.json").write_text(json.dumps(planning, indent=2), encoding="utf-8")

    canon_dir = data / "canon_versions" / "chapter_001"
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / "index.json").write_text(
        json.dumps({"canon_version_id": "canon-ch1-v1", "revision_id": "rev-001", "active": True}),
        encoding="utf-8",
    )

    manifest_dir = chroma_dir / "manifests" / "main"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "branch_alpha.json").write_text(
        json.dumps({"vector_ready": True, "branch_lifecycle_status": "open", "canon_revision_id": "rev-001"}),
        encoding="utf-8",
    )

    return {"project_id": root.name, "timeline_id": "main", "branch_id": "branch_alpha", "chapter_id": 2}


def _make_fixture_c(root: Path) -> dict:
    """Fixture C: Branch isolation.

    Branch A Chapter 1 committed, Branch B has different state, Chapter 2 absent.
    """
    data = root / "data"
    chapters_dir = data / "chapters"
    versions_dir = data / "versions"
    branches_dir = data / "branches"
    chroma_dir = data / "chroma"
    planning_dir = data / "planning_control"

    for d in (chapters_dir, versions_dir, branches_dir, chroma_dir, planning_dir, data / "state"):
        d.mkdir(parents=True, exist_ok=True)

    (chapters_dir / "chapter_001.md").write_text("# Chapter 1\nCommitted content.", encoding="utf-8")

    v1_dir = versions_dir / "chapter_001"
    v1_dir.mkdir(parents=True, exist_ok=True)
    (v1_dir / "manual_v001.md").write_text("# Manual v001\nChapter 1 source.", encoding="utf-8")
    (v1_dir / "chapter_001_versions.json").write_text(
        json.dumps({"selected": {"version_label": "manual_v001", "source_type": "manual", "version": 1}}),
        encoding="utf-8",
    )

    state_file = data / "state" / "state.json"
    state_file.write_text(json.dumps({"current_chapter": 1}), encoding="utf-8")

    branch_dir = branches_dir / "main"
    branch_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "active_branch_id": "branch_alpha",
        "registry_revision": "rev-002",
        "branches": {
            "branch_alpha": {
                "branch_id": "branch_alpha",
                "display_name": "Alpha",
                "lifecycle_status": "open",
                "is_active": True,
            },
            "branch_beta": {
                "branch_id": "branch_beta",
                "display_name": "Beta",
                "lifecycle_status": "archived",
                "is_active": False,
            },
        },
    }
    (branch_dir / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")

    canon_dir = data / "canon_versions" / "chapter_001"
    canon_dir.mkdir(parents=True, exist_ok=True)
    (canon_dir / "index.json").write_text(
        json.dumps({"canon_version_id": "canon-ch1-v1", "revision_id": "rev-001", "active": True}),
        encoding="utf-8",
    )

    for branch_id in ("branch_alpha", "branch_beta"):
        manifest_dir = chroma_dir / "manifests" / "main"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"{branch_id}.json").write_text(
            json.dumps({"vector_ready": True, "branch_lifecycle_status": "open", "canon_revision_id": "rev-001"}),
            encoding="utf-8",
        )

    return {"project_id": root.name, "timeline_id": "main", "branch_id": "branch_alpha", "chapter_id": 2}


def _probe(root: Path, fixture_spec: dict, label: str) -> dict:
    """Run read-only probes against a fixture and report findings."""
    print(f"\n{'='*60}")
    print(f"Fixture {label}: Probe sequence")
    print(f"{'='*60}")

    context = get_project_context(root)

    before = _sha256_manifest(root)

    print("\n[Probe 1] list_versions(chapter_id=2) ...")
    try:
        versions = list_versions(2, context.data_dir)
        print(f"  Result: {json.dumps({k: len(v) if isinstance(v, list) else v for k, v in versions.items()}, default=str)}")
    except Exception as exc:
        print(f"  Error: {exc}")

    after_p1 = _sha256_manifest(root)
    diff_p1 = _diff_manifest(before, after_p1)
    print(f"  Files changed: {len(diff_p1)}")
    for key, (b, a) in list(diff_p1.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    print("\n[Probe 2] get_selected_version(chapter_id=2) ...")
    before_p2 = _sha256_manifest(root)
    try:
        selected = get_selected_version(2, context.data_dir)
        print(f"  Result: {json.dumps(selected, default=str)}")
    except Exception as exc:
        print(f"  Error: {exc}")
    after_p2 = _sha256_manifest(root)
    diff_p2 = _diff_manifest(before_p2, after_p2)
    print(f"  Files changed: {len(diff_p2)}")
    for key, (b, a) in list(diff_p2.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    print("\n[Probe 3] RevisionService.read_active_canon(chapter_id=2) ...")
    before_p3 = _sha256_manifest(root)
    svc = RevisionService(context)
    try:
        canon = svc.read_active_canon(2)
        print(f"  Result: {json.dumps(canon, default=str)}")
    except Exception as exc:
        print(f"  Error: {exc}")
    after_p3 = _sha256_manifest(root)
    diff_p3 = _diff_manifest(before_p3, after_p3)
    print(f"  Files changed: {len(diff_p3)}")
    for key, (b, a) in list(diff_p3.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    print("\n[Probe 4] RevisionService.active_canon(chapter_id=2) ...")
    before_p4 = _sha256_manifest(root)
    try:
        canon = svc.active_canon(2)
        print(f"  Result: {json.dumps(canon, default=str)}")
    except Exception as exc:
        print(f"  Error: {exc}")
    after_p4 = _sha256_manifest(root)
    diff_p4 = _diff_manifest(before_p4, after_p4)
    print(f"  Files changed: {len(diff_p4)}")
    for key, (b, a) in list(diff_p4.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    print("\n[Probe 5] SimulatorLoopStateService.build() ...")
    before_p5 = _sha256_manifest(root)
    try:
        svc2 = SimulatorLoopStateService(context)
        state = svc2.build(
            project_id=fixture_spec["project_id"],
            timeline_id=fixture_spec["timeline_id"],
            chapter_id=fixture_spec["chapter_id"],
            branch_id=fixture_spec["branch_id"],
        )
        cd = state.chapter_progression
        print(f"  chapter_progression: {json.dumps(cd, default=str)}")
        print(f"  stage: {state.current_stage}")
        print(f"  branch readiness: {state.branch.get('readiness')}")
        print(f"  turn current_turn: {state.turn.get('current_turn')}")
        print(f"  candidate list count: {len(state.candidate.get('candidate_list', []))}")
    except Exception as exc:
        print(f"  Error: {type(exc).__name__}: {exc}")
    after_p5 = _sha256_manifest(root)
    diff_p5 = _diff_manifest(before_p5, after_p5)
    print(f"  Files changed: {len(diff_p5)}")
    for key, (b, a) in list(diff_p5.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    print("\n[Probe 6] Planning load_planning() ...")
    before_p6 = _sha256_manifest(root)
    try:
        planning = load_planning(context)
        print(f"  Result: {json.dumps(planning, default=str)[:300]}")
    except Exception as exc:
        print(f"  Error: {exc}")
    after_p6 = _sha256_manifest(root)
    diff_p6 = _diff_manifest(before_p6, after_p6)
    print(f"  Files changed: {len(diff_p6)}")
    for key, (b, a) in list(diff_p6.items())[:5]:
        print(f"    {key}: {b[:16]}... -> {a[:16]}...")

    final = _sha256_manifest(root)
    total_diff = _diff_manifest(before, final)
    print(f"\n[Final] Total files changed from start to end: {len(total_diff)}")
    for key, (b, a) in sorted(total_diff.items()):
        print(f"  {key}: {b[:24]}... -> {a[:24]}...")

    return {
        "label": label,
        "total_files_changed": len(total_diff),
        "diff": {k: {"before": v[0], "after": v[1]} for k, v in total_diff.items()},
        "chapter_progression": cd if "cd" in dir() else None,
    }


def main() -> None:
    results: list[dict] = []
    probes_dir = Path(tempfile.mkdtemp(prefix="storyos-0d6p-probes-"))

    try:
        fixture_a_dir = probes_dir / "fixture_a"
        fixture_a_dir.mkdir()
        spec_a = _make_fixture_a(fixture_a_dir)
        results.append(_probe(fixture_a_dir, spec_a, "A (next chapter exists)"))

        fixture_b_dir = probes_dir / "fixture_b"
        fixture_b_dir.mkdir()
        spec_b = _make_fixture_b(fixture_b_dir)
        results.append(_probe(fixture_b_dir, spec_b, "B (next chapter absent)"))

        fixture_c_dir = probes_dir / "fixture_c"
        fixture_c_dir.mkdir()
        spec_c = _make_fixture_c(fixture_c_dir)
        results.append(_probe(fixture_c_dir, spec_c, "C (branch isolation)"))

        print("\n" + "=" * 60)
        print("SUMMARY OF ALL FIXTURE PROBES")
        print("=" * 60)
        for r in results:
            print(f"\nFixture {r['label']}:")
            print(f"  Total files changed: {r['total_files_changed']}")
            if r.get("chapter_progression"):
                cp = r["chapter_progression"]
                print(f"  next_chapter_available: {cp.get('next_chapter_available')}")
                print(f"  next_chapter_id: {cp.get('next_chapter_id')}")
    finally:
        shutil.rmtree(probes_dir, ignore_errors=True)
        print(f"\n[Cleanup] Deleted temporary probe directory: {probes_dir}")


if __name__ == "__main__":
    main()