"""Verify durable evidence produced by the real Chromium Phase 0D5 final run.

Chromium drives every UI action. This reads only the isolated fixture left by
that run; it is not a browser substitute.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _records(root: Path, pattern: str) -> list[dict]:
    values = []
    for path in root.glob(pattern):
        try:
            values.append(_json(path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True)
    root = Path(parser.parse_args().evidence_root).resolve()
    counts = _json(root / ".drc1_network_audit.json")["requests"]
    turns = _records(root, "data/narrative_turn/results/*/*/*.json")
    candidates = [
        item for item in _records(root, "data/manual/*.json")
        if item.get("narrative_compilation")
    ]
    reviews = _records(root, "data/narrative_candidate_review/decisions/*.json")
    commits = _records(root, "data/narrative_compile/commit_operations/*.result.json")
    checks = {
        "SIMULATOR_FULL_USABLE_LOOP": (
            counts["confirm"] == 2 and counts["compile"] == 1
            and counts["review"] == 1 and counts["commit"] == 1
        ),
        "BRANCH_PRODUCT_LOOP": (
            counts["branch_create"] == 1 and counts["branch_select"] == 1
            and counts["branch_archive"] == 1 and counts["branch_restore"] == 1
        ),
        "MULTI_TURN_HISTORY": len(turns) == 2,
        "CANDIDATE_REVIEW_COMMIT_COMPLETE": (
            len(candidates) == 1 and len(reviews) == 1
            and any(item.get("decision") == "approved" for item in reviews)
            and len(commits) == 1
        ),
    }
    for label, passed in checks.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
