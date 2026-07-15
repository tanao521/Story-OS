"""Read-only validation and review-pack generation for planning recovery.

The utility inventories candidate copies and creates reports only under an
explicit artifact directory.  It has no operation that writes official data
files, selects a new baseline, or restores a candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

try:  # Supports both ``python -m tools...`` and direct script execution.
    from tools.data_recovery import sha256
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI itself
    from data_recovery import sha256


TARGETS = ("story_blueprint", "next_chapter_plan")
SHA256_LENGTH = 64


def _digest(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:16]


def read_expected_hashes(path: Path) -> dict[str, str]:
    """Read, normalize, and validate the recorded pre-test hashes."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    aliases = {
        "story_blueprint": ("story_blueprint", "expected_story_blueprint_sha256"),
        "next_chapter_plan": ("next_chapter_plan", "expected_next_chapter_plan_sha256"),
    }
    expected: dict[str, str] = {}
    for target, names in aliases.items():
        value = next((raw[name] for name in names if name in raw), None)
        if not isinstance(value, str) or len(value) != SHA256_LENGTH or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError(f"INVALID_EXPECTED_SHA256:{target}")
        expected[target] = value.upper()
    return expected


def _document_type(document: dict[str, Any]) -> str:
    blueprint_signals = {"blueprint_version", "chapter_plan", "story_phases", "main_arc", "core_premise", "character_bible", "world_direction"}
    plan_signals = {"plan_version", "chapter_id", "chapter_goal", "scene_plan", "required_context", "phase_position", "continuity_constraints"}
    blueprint_score = len(blueprint_signals & set(document))
    plan_score = len(plan_signals & set(document))
    if "chapter_id" in document and plan_score >= 2 and plan_score >= blueprint_score:
        return "next_chapter_plan"
    if blueprint_score >= 2 and blueprint_score > plan_score:
        return "story_blueprint"
    return "unknown"


def _schema_status(target: str, document: dict[str, Any]) -> str:
    if target == "story_blueprint":
        return "valid_current" if {"blueprint_version", "chapter_plan"}.issubset(document) else "valid_legacy"
    if target == "next_chapter_plan":
        return "valid_current" if {"plan_version", "chapter_id"}.issubset(document) else "valid_legacy"
    return "unknown"


def _summary(target: str, document: dict[str, Any]) -> dict[str, Any]:
    meta = document.get("generation_meta")
    meta_summary = {"present": isinstance(meta, dict), "keys": sorted(meta)[:20] if isinstance(meta, dict) else []}
    if isinstance(meta, dict) and isinstance(meta.get("mode"), str):
        meta_summary["mode"] = meta["mode"]
    if target == "story_blueprint":
        return {
            "top_level_keys": sorted(document)[:50],
            "chapter_plan_count": len(document.get("chapter_plan", [])) if isinstance(document.get("chapter_plan"), list) else None,
            "story_phase_count": len(document.get("story_phases", [])) if isinstance(document.get("story_phases"), list) else None,
            "title_digest": _digest(document.get("title")) if "title" in document else None,
            "project_id_digest": _digest(document.get("project_id")) if "project_id" in document else None,
            "generation_meta": meta_summary,
        }
    if target == "next_chapter_plan":
        return {
            "top_level_keys": sorted(document)[:50],
            "chapter_id": document.get("chapter_id") if isinstance(document.get("chapter_id"), int) else None,
            "chapter_title_digest": _digest(document.get("chapter_title")) if "chapter_title" in document else None,
            "project_id_digest": _digest(document.get("project_id")) if "project_id" in document else None,
            "scene_plan_count": len(document.get("scene_plan", [])) if isinstance(document.get("scene_plan"), list) else None,
            "generation_meta": meta_summary,
        }
    return {"top_level_keys": sorted(document)[:50]}


def validate_candidate(path: Path, source_category: str, expected: dict[str, str], *, expected_hint: str | None = None) -> dict[str, Any]:
    """Inspect one file without mutating it; type is based on JSON structure."""
    path = path.resolve()
    stat = path.stat()
    row: dict[str, Any] = {
        "candidate_id": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
        "absolute_source_path": str(path), "source_category": source_category,
        "filename": path.name, "size": stat.st_size,
        "created_time": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
        "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path), "json_status": "invalid_json", "target_type": "unknown",
        "schema_status": "invalid_json", "exact_match": False, "summary": {},
    }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return row
    if not isinstance(document, dict):
        row["json_status"] = "wrong_target_type"
        row["schema_status"] = "wrong_target_type"
        return row
    target = _document_type(document)
    row["target_type"] = target
    row["summary"] = _summary(target, document)
    if target == "unknown":
        row["json_status"] = "wrong_target_type"
        row["schema_status"] = "unknown"
        return row
    if expected_hint and expected_hint != target:
        row["json_status"] = "wrong_target_type"
        row["schema_status"] = "wrong_target_type"
        return row
    row["json_status"] = "valid_json"
    row["schema_status"] = _schema_status(target, document)
    row["exact_match"] = row["sha256"] == expected[target]
    return row


def merge_duplicate_candidates(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate content by target and SHA while retaining every source path."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["target_type"], row["sha256"])
        if key not in grouped:
            grouped[key] = {**row, "source_paths": [row["absolute_source_path"]], "source_categories": [row["source_category"]]}
            continue
        existing = grouped[key]
        existing["source_paths"].append(row["absolute_source_path"])
        if row["source_category"] not in existing["source_categories"]:
            existing["source_categories"].append(row["source_category"])
    return sorted(grouped.values(), key=lambda row: (row["target_type"], row["sha256"], row["candidate_id"]))


def discover_vscode_history(history_root: Path, targets: Iterable[Path]) -> tuple[list[Path], dict[str, int]]:
    """Read only VS Code entries.json mappings that explicitly point at targets."""
    expected_paths = {str(path.resolve()).casefold() for path in targets}
    candidates: list[Path] = []
    checked = matched = malformed = 0
    if not history_root.is_dir():
        return candidates, {"entries_checked": checked, "mappings_matched": matched, "malformed_entries": malformed}
    for entries in history_root.rglob("entries.json"):
        checked += 1
        try:
            record = json.loads(entries.read_text(encoding="utf-8"))
            resource = record.get("resource")
            if not isinstance(resource, str):
                continue
            parsed = urlparse(resource)
            local = Path(unquote(parsed.path.lstrip("/"))) if parsed.scheme == "file" else Path(resource)
            if str(local.resolve()).casefold() not in expected_paths:
                continue
            history_entries = record.get("entries", [])
            if not isinstance(history_entries, list):
                malformed += 1
                continue
            matched += 1
            for item in history_entries:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                snapshot = entries.parent / item["id"]
                if snapshot.is_file():
                    candidates.append(snapshot)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            malformed += 1
    return candidates, {"entries_checked": checked, "mappings_matched": matched, "malformed_entries": malformed}


def _extract_ids(value: Any, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item[key]) for item in value if isinstance(item, dict) for key in keys if key in item and isinstance(item[key], (str, int))}


def pair_compatibility(blueprint: dict[str, Any], plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Assess a pair structurally; it never ranks or selects candidates."""
    checks: list[dict[str, str]] = []
    def add(name: str, status: str) -> None: checks.append({"check": name, "status": status})
    bp_project, plan_project = blueprint.get("project_id"), plan.get("project_id")
    if bp_project is not None and plan_project is not None:
        add("project_id", "pass" if bp_project == plan_project else "fail")
    else: add("project_id", "unknown")
    bp_title, plan_title = blueprint.get("title"), plan.get("story_title")
    if isinstance(bp_title, str) and isinstance(plan_title, str): add("title", "pass" if bp_title == plan_title else "attention")
    else: add("title", "unknown")
    chapter_id = plan.get("chapter_id")
    planned_ids = _extract_ids(blueprint.get("chapter_plan"), ("chapter_id", "id"))
    if isinstance(chapter_id, int) and planned_ids: add("chapter_reference", "pass" if str(chapter_id) in planned_ids else "attention")
    else: add("chapter_reference", "unknown")
    phase = plan.get("phase_position")
    phase_id = phase.get("phase_id") if isinstance(phase, dict) else None
    phases = _extract_ids(blueprint.get("story_phases"), ("phase_id", "id"))
    if phase_id is not None and phases: add("phase_reference", "pass" if str(phase_id) in phases else "fail")
    else: add("phase_reference", "unknown")
    current_chapter = state.get("current_chapter")
    if isinstance(chapter_id, int) and isinstance(current_chapter, int): add("state_progress", "pass" if chapter_id in {current_chapter, current_chapter + 1} else "attention")
    else: add("state_progress", "unknown")
    statuses = {entry["status"] for entry in checks}
    status = "incompatible" if "fail" in statuses else "insufficient_evidence" if statuses == {"unknown"} else "attention" if {"attention", "unknown"} & statuses else "compatible"
    return {"status": status, "checks": checks, "manual_review_only": True}


def _copy_for_review(row: dict[str, Any], destination: Path) -> None:
    source = Path(row["absolute_source_path"])
    target = destination / f"{row['candidate_id']}-{source.name}"
    if not target.exists():
        shutil.copy2(source, target)
    if sha256(target) != row["sha256"]:
        raise RuntimeError("CANDIDATE_COPY_HASH_MISMATCH")


def _safe_top_level_diff(current: Path, candidate: Path) -> dict[str, Any]:
    """Report shape changes only, never candidate prose or field values."""
    left = json.loads(current.read_text(encoding="utf-8"))
    right = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(left, dict) or not isinstance(right, dict):
        return {"status": "not_comparable"}
    left_keys, right_keys = set(left), set(right)
    changed = sorted(key for key in left_keys & right_keys if left[key] != right[key])
    return {"status": "comparable", "only_in_current": sorted(left_keys - right_keys), "only_in_candidate": sorted(right_keys - left_keys), "changed_top_level_fields": changed}


def build_review_pack(*, project_root: Path, previous_hashes: Path, manual_dir: Path, artifact_dir: Path, vscode_roots: Iterable[Path], onedrive_root: Path | None) -> dict[str, Any]:
    """Create a local review package; never alters project data or candidates."""
    expected = read_expected_hashes(previous_hashes)
    project_root, manual_dir, artifact_dir = project_root.resolve(), manual_dir.resolve(), artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name in ("candidates", "exact_matches", "reports", "diffs"):
        (artifact_dir / name).mkdir(exist_ok=True)
    targets = [project_root / "data" / "story_blueprint.json", project_root / "data" / "next_chapter_plan.json"]
    source_specs: list[tuple[Path, str, str | None]] = [(targets[0], "current", "story_blueprint"), (targets[1], "current", "next_chapter_plan")]
    for candidate in sorted((project_root / ".artifacts" / "data-recovery-15-3a-2" / "candidates").glob("*")):
        if candidate.is_file() and candidate.name != "manifest.json": source_specs.append((candidate, "prior_recovery_artifact", None))
    if manual_dir.is_dir():
        for candidate in sorted(manual_dir.iterdir()):
            if candidate.is_file(): source_specs.append((candidate, "manual_export", None))
    vscode_report: dict[str, Any] = {"roots": []}
    for root in vscode_roots:
        discovered, metadata = discover_vscode_history(root, targets)
        vscode_report["roots"].append({"path": str(root), "exists": root.is_dir(), **metadata, "candidate_count": len(discovered)})
        source_specs.extend((candidate, "vscode_history", None) for candidate in discovered)
    onedrive_matches: list[Path] = []
    if onedrive_root and onedrive_root.is_dir():
        names = {"story_blueprint.json", "next_chapter_plan.json"}
        onedrive_matches = [path for name in names for path in onedrive_root.rglob(name)]
        source_specs.extend((candidate, "onedrive_replica", None) for candidate in onedrive_matches)
    rows = [validate_candidate(path, category, expected, expected_hint=hint) for path, category, hint in source_specs if path.is_file()]
    merged = merge_duplicate_candidates(rows)
    for row in merged:
        _copy_for_review(row, artifact_dir / "candidates")
        if row["exact_match"]: _copy_for_review(row, artifact_dir / "exact_matches")
    summaries = [{"candidate_id": row["candidate_id"], "target_type": row["target_type"], "json_status": row["json_status"], "schema_status": row["schema_status"], "summary": row["summary"]} for row in merged]
    for row in merged:
        if row["target_type"] not in TARGETS or row["json_status"] != "valid_json":
            continue
        current = project_root / "data" / ("story_blueprint.json" if row["target_type"] == "story_blueprint" else "next_chapter_plan.json")
        if current.is_file():
            diff_path = artifact_dir / "diffs" / f"{row['candidate_id']}.json"
            diff_path.write_text(json.dumps(_safe_top_level_diff(current, Path(row["absolute_source_path"])), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path = project_root / "data" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    blueprints = [row for row in merged if row["target_type"] == "story_blueprint" and row["json_status"] == "valid_json"]
    plans = [row for row in merged if row["target_type"] == "next_chapter_plan" and row["json_status"] == "valid_json"]
    pairs = []
    for blueprint in blueprints:
        for plan in plans:
            bp_json = json.loads(Path(blueprint["absolute_source_path"]).read_text(encoding="utf-8"))
            plan_json = json.loads(Path(plan["absolute_source_path"]).read_text(encoding="utf-8"))
            pairs.append({"blueprint_candidate_id": blueprint["candidate_id"], "next_plan_candidate_id": plan["candidate_id"], **pair_compatibility(bp_json, plan_json, state)})
    exact = {target: [row["candidate_id"] for row in merged if row["target_type"] == target and row["exact_match"]] for target in TARGETS}
    readiness = "ready_for_exact_restore" if all(exact.values()) else "partial_exact_match" if any(exact.values()) else "no_exact_match"
    (artifact_dir / "inventory.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "exact_match_report.json").write_text(json.dumps({"expected": expected, "exact_matches": exact, "recovery_readiness": readiness}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "baseline_pair_report.json").write_text(json.dumps({"pairs": pairs, "automatic_selection": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "reports" / "structural_summaries.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "reports" / "history_sources.json").write_text(json.dumps({"vscode": vscode_report, "jetbrains": "requires_ui_export", "onedrive": {"root": str(onedrive_root) if onedrive_root else None, "local_same_name_candidates": len(onedrive_matches), "requires_ui_export": True}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "baseline_selection.template.json").write_text(json.dumps({"approved": False, "acknowledge_original_not_recovered": False, "story_blueprint_candidate_id": "", "next_chapter_plan_candidate_id": "", "approval_reason": "", "approved_by": "user", "approved_at": ""}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "recovery_preview.md").write_text("# Recovery preview\n\nThis is read-only evidence. No official data file was restored or selected.\n\n- recovery_readiness: " + readiness + "\n- automatic baseline selection: false\n", encoding="utf-8")
    return {"expected": expected, "candidate_count": len(merged), "valid_blueprints": len(blueprints), "valid_plans": len(plans), "exact": exact, "readiness": readiness, "pairs": pairs, "vscode": vscode_report, "onedrive_matches": len(onedrive_matches)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only planning history review pack")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--previous-hashes", required=True)
    parser.add_argument("--manual-dir", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--vscode-history", action="append", default=[])
    parser.add_argument("--onedrive-root")
    args = parser.parse_args()
    result = build_review_pack(project_root=Path(args.project_root), previous_hashes=Path(args.previous_hashes), manual_dir=Path(args.manual_dir), artifact_dir=Path(args.artifact_dir), vscode_roots=[Path(value) for value in args.vscode_history], onedrive_root=Path(args.onedrive_root) if args.onedrive_root else None)
    print(json.dumps({"candidate_count": result["candidate_count"], "recovery_readiness": result["readiness"], "pair_count": len(result["pairs"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
