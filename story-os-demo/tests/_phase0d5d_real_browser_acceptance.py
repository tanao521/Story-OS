"""Verify durable evidence captured by the real Chromium D-RC1 matrix.

The Browser runtime drives the clicks, history, DOM, and console checks. This
small operator-facing verifier reads only the isolated fixture evidence left by
that session; it never substitutes TestClient or labels a static DOM check as
browser evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _latest_root() -> Path | None:
    roots = sorted(
        Path(os.environ.get("TEMP", ".")).glob("rc2_browser_ws_*/projects/rc2-test-project"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return roots[0] if roots else None


def _audit(root: Path) -> dict:
    return json.loads((root / ".drc1_network_audit.json").read_text(encoding="utf-8"))


def _candidate_payloads(root: Path) -> list[dict]:
    values = []
    for path in (root / "data" / "manual").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if payload.get("narrative_compilation"):
            values.append(payload)
    return values


def _decisions(root: Path) -> list[dict]:
    values = []
    for path in (root / "data" / "narrative_candidate_review" / "decisions").glob("*.json"):
        try:
            values.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return values


def verify(root: Path, scenario: str) -> bool:
    audit = _audit(root)
    requests = audit.get("requests", {})
    dropped = set(audit.get("dropped", []))
    candidates = _candidate_payloads(root)
    decisions = _decisions(root)
    if scenario == "reject":
        passed = requests == {"compile": 1, "review": 1, "commit": 0} and any(item.get("decision") == "rejected" for item in decisions)
        label = "REJECT_BLOCKS_COMMIT"
    elif scenario == "compile":
        passed = requests == {"compile": 1, "review": 0, "commit": 0} and dropped == {"compile"} and any(
            item.get("review_status") == "pending" or item.get("narrative_compilation", {}).get("review_status") == "pending"
            for item in candidates
        )
        label = "COMPILE_RESPONSE_LOSS_RECOVERY"
    elif scenario == "review":
        passed = requests == {"compile": 1, "review": 1, "commit": 0} and dropped == {"review"} and any(item.get("decision") == "approved" for item in decisions)
        label = "REVIEW_RESPONSE_LOSS_RECOVERY"
    elif scenario == "commit":
        from core.project_context import get_project_context
        from system.simulator_loop_state import SimulatorLoopStateService

        project = root
        context = get_project_context(project)
        state = SimulatorLoopStateService(context).build(
            project_id=project.name, timeline_id="tl-main", branch_id="root", chapter_id=1
        ).to_dict()
        passed = requests == {"compile": 1, "review": 1, "commit": 1} and dropped == {"commit"} and state["chapter_progression"]["completed"] and state["approval"]["can_commit"] is False
        label = "COMMIT_RESPONSE_LOSS_RECOVERY"
    else:
        raise ValueError(f"unsupported scenario: {scenario}")
    print(f"{label}: {'PASS' if passed else 'EVIDENCE_REQUIRED'}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=("reject", "compile", "review", "commit"))
    parser.add_argument("--evidence-root", default="")
    args = parser.parse_args()
    root = Path(args.evidence_root) if args.evidence_root else _latest_root()
    if root is None:
        print("fixture evidence unavailable")
        return 1
    return 0 if verify(root, args.scenario) else 1


if __name__ == "__main__":
    raise SystemExit(main())
