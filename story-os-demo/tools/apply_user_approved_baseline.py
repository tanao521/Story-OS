"""Apply an explicitly approved planning baseline from local evidence copies.

This command is intentionally narrow: both candidate IDs must be supplied,
the source must be an evidence copy, and every preflight check completes before
either official file is atomically replaced.  It never modifies state or any
other planning artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # Direct ``python tools/...py`` invocation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.project_context import get_project_context
from system.data_store import DataStore

try:
    from tools.data_recovery import sha256
    from tools.manual_history_recovery import validate_candidate
except ModuleNotFoundError:  # Supports direct script execution.
    from data_recovery import sha256
    from manual_history_recovery import validate_candidate


TARGET_PATHS = {
    "story_blueprint": Path("data/story_blueprint.json"),
    "next_chapter_plan": Path("data/next_chapter_plan.json"),
}


def _read_inventory(path: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("INVALID_RECOVERY_INVENTORY")
    return {row["candidate_id"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)}


def _evidence_copy(candidates_dir: Path, candidate_id: str) -> Path:
    matches = sorted(path for path in candidates_dir.glob(f"{candidate_id}-*") if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"EVIDENCE_COPY_NOT_UNIQUE:{candidate_id}")
    return matches[0]


def _preflight(inventory: dict[str, dict[str, Any]], candidates_dir: Path, candidate_id: str, target: str) -> tuple[dict[str, Any], Path, str]:
    row = inventory.get(candidate_id)
    if not row or row.get("target_type") != target or row.get("json_status") != "valid_json":
        raise ValueError(f"INVALID_APPROVED_CANDIDATE:{candidate_id}")
    candidate = _evidence_copy(candidates_dir, candidate_id)
    if sha256(candidate) != row.get("sha256"):
        raise ValueError(f"EVIDENCE_SHA_MISMATCH:{candidate_id}")
    validated = validate_candidate(candidate, "evidence_copy", {target: row["sha256"], **({"next_chapter_plan": "0" * 64} if target == "story_blueprint" else {"story_blueprint": "0" * 64})})
    if validated["target_type"] != target or validated["json_status"] != "valid_json":
        raise ValueError(f"EVIDENCE_JSON_TYPE_INVALID:{candidate_id}")
    text = candidate.read_bytes().decode("utf-8")
    json.loads(text)  # Verify parseability without changing source bytes.
    return row, candidate, text


def apply_user_approved_baseline(*, project_root: Path, recovery_artifact: Path, incident_dir: Path, story_blueprint_candidate_id: str, next_chapter_plan_candidate_id: str) -> dict[str, Any]:
    """Back up current planning files then atomically apply approved evidence."""
    project_root = project_root.resolve()
    recovery_artifact = recovery_artifact.resolve()
    inventory = _read_inventory(recovery_artifact / "inventory.json")
    candidates_dir = recovery_artifact / "candidates"
    blueprint_row, blueprint_source, blueprint_text = _preflight(inventory, candidates_dir, story_blueprint_candidate_id, "story_blueprint")
    plan_row, plan_source, plan_text = _preflight(inventory, candidates_dir, next_chapter_plan_candidate_id, "next_chapter_plan")
    context = get_project_context(project_root)
    store = DataStore(context)
    official = {target: context.root / relative for target, relative in TARGET_PATHS.items()}
    state_path = context.root / "data/state.json"
    state_before = sha256(state_path)
    originals = {target: sha256(path) for target, path in official.items()}
    incident_dir.mkdir(parents=True, exist_ok=True)
    backup_paths: dict[str, Path] = {}
    for target, path in official.items():
        backup = incident_dir / f"pre-user-approved-baseline-{path.name}"
        shutil.copy2(path, backup)
        if sha256(backup) != originals[target]:
            raise RuntimeError(f"INCIDENT_BACKUP_HASH_MISMATCH:{target}")
        backup_paths[target] = backup
    # DataStore is the project's fsync + os.replace implementation.  backup is
    # false so this authorized replacement cannot create a new official .bak.
    store._atomic(TARGET_PATHS["story_blueprint"], blueprint_text, backup=False)
    store._atomic(TARGET_PATHS["next_chapter_plan"], plan_text, backup=False)
    final_hashes = {target: sha256(path) for target, path in official.items()}
    if final_hashes["story_blueprint"] != blueprint_row["sha256"] or final_hashes["next_chapter_plan"] != plan_row["sha256"]:
        raise RuntimeError("APPLIED_BASELINE_HASH_MISMATCH")
    if sha256(state_path) != state_before:
        raise RuntimeError("STATE_CHANGED_DURING_BASELINE_APPLICATION")
    plan = json.loads(official["next_chapter_plan"].read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if plan.get("chapter_id") != 7 or state.get("current_chapter") != 6:
        raise RuntimeError("APPROVED_BASELINE_PROGRESS_VALIDATION_FAILED")
    audit = {
        "baseline_type": "user_approved_new_baseline",
        "original_version_recovered": False,
        "approved_candidate_ids": {"story_blueprint": story_blueprint_candidate_id, "next_chapter_plan": next_chapter_plan_candidate_id},
        "candidate_sources": {"story_blueprint": str(blueprint_source), "next_chapter_plan": str(plan_source)},
        "original_hashes": originals,
        "applied_hashes": final_hashes,
        "incident_backups": {target: str(path) for target, path in backup_paths.items()},
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    (incident_dir / "user-approved-baseline-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply an explicitly user-approved Story OS planning baseline")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--recovery-artifact", required=True)
    parser.add_argument("--incident-dir", required=True)
    parser.add_argument("--story-blueprint-candidate-id", required=True)
    parser.add_argument("--next-chapter-plan-candidate-id", required=True)
    args = parser.parse_args()
    audit = apply_user_approved_baseline(project_root=Path(args.project_root), recovery_artifact=Path(args.recovery_artifact), incident_dir=Path(args.incident_dir), story_blueprint_candidate_id=args.story_blueprint_candidate_id, next_chapter_plan_candidate_id=args.next_chapter_plan_candidate_id)
    print(json.dumps({"baseline_type": audit["baseline_type"], "applied_hashes": audit["applied_hashes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
