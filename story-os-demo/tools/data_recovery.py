"""Read-only candidate inventory for exact-hash Story OS data recovery.

This tool never writes a source candidate or an official ``data/`` file.  It
only emits metadata and, when requested, copies exact matches into a separate
evidence directory for human review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TARGETS = {
    "story_blueprint": "story_blueprint.json",
    "next_chapter_plan": "next_chapter_plan.json",
}
REQUIRED_TOP_LEVEL_KEYS = {
    "story_blueprint": {"blueprint_version"},
    "next_chapter_plan": {"plan_version"},
}
EXCLUDED_PARTS = {".git", ".venv", "node_modules"}
_PYTEST_RUN_PART = re.compile(r"pytest-(?:\d+|current)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _target_for(path: Path) -> str | None:
    name = path.name.lower()
    if "schema" in name:
        return None
    if "story_blueprint" in name or "blueprint" in name:
        return "story_blueprint"
    if "next_chapter_plan" in name or "chapter_plan" in name:
        return "next_chapter_plan"
    return None


def _is_pytest_temporary_path(path: Path) -> bool:
    """Return whether *path* is inside a known pytest-created directory.

    This is deliberately based on complete path components rather than a
    substring search: recovery scans must still accept project names such as
    ``pytest-novel-project`` and ``temporary-kingdom``.
    """
    normalized = Path(os.path.normpath(os.fspath(path)))
    parts = [part.casefold() for part in normalized.parts]
    if any(part.startswith(".pytest-tmp-phase-") for part in parts):
        return True
    if any(part.startswith("storyos-pytest-") for part in parts):
        return True

    for index, part in enumerate(parts):
        if part.startswith("pytest-of-") and any(
            _PYTEST_RUN_PART.fullmatch(child) for child in parts[index + 1 :]
        ):
            return True
        if part.startswith("storyos-phase-") and any(
            child in {"pytest-temp", "diagnostic-temp"} for child in parts[index + 1 :]
        ):
            return True
    return False


def _allowed(path: Path, excluded_roots: Iterable[Path]) -> bool:
    if path.is_symlink() or _is_pytest_temporary_path(path):
        return False
    if any(part.casefold() in EXCLUDED_PARTS for part in path.parts):
        return False
    return not any(path == root or root in path.parents for root in excluded_roots)


def inventory(roots: Iterable[Path], expected: dict[str, str], *, excluded_roots: Iterable[Path] = ()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not _allowed(root, excluded_roots) or not root.exists() or not root.is_dir():
            continue
        for directory, names, files in os.walk(root, followlinks=False):
            current = Path(directory)
            names[:] = [name for name in names if _allowed(current / name, excluded_roots)]
            for filename in files:
                path = current / filename
                if not _allowed(path, excluded_roots):
                    continue
                if path.suffix.lower() not in {".json", ".bak", ".tmp", ".backup", ".old"}:
                    continue
                target = _target_for(path)
                if not target:
                    continue
                value = sha256(path)
                try:
                    parsed = json.loads(path.read_text(encoding="utf-8"))
                    json_valid = isinstance(parsed, dict)
                    keys = sorted(parsed)[:30] if json_valid else []
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    json_valid, keys = False, []
                target_schema_valid = json_valid and REQUIRED_TOP_LEVEL_KEYS[target].issubset(parsed)
                stat = path.stat()
                rows.append({
                    "candidate_id": hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16],
                    "target_file": TARGETS[target], "absolute_source_path": str(path.resolve()),
                    "source_category": "artifact" if ".artifacts" in path.parts else "filesystem",
                    "filename": path.name, "size": stat.st_size,
                    "created_time": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
                    "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "sha256": value, "json_valid": json_valid,
                    "target_schema_valid": target_schema_valid,
                    "top_level_keys": keys,
                    "matches_expected_pretest_sha": target_schema_valid and value == expected.get(target, ""),
                })
    return sorted(rows, key=lambda row: (row["target_file"], row["absolute_source_path"]))


def write_evidence(rows: list[dict[str, Any]], artifact_dir: Path, expected: dict[str, str]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "inventory.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "hashes.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    exact_dir = artifact_dir / "exact_matches"; exact_dir.mkdir(exist_ok=True)
    for row in rows:
        if row["matches_expected_pretest_sha"]:
            source = Path(row["absolute_source_path"])
            target = exact_dir / f"{row['candidate_id']}-{source.name}"
            shutil.copy2(source, target)
            if sha256(target) != row["sha256"]:
                raise RuntimeError("EXACT_MATCH_COPY_HASH_MISMATCH")


def structural_diff(current: Path, candidate: Path) -> dict[str, Any]:
    """Return a content-safe JSON structure comparison for human review."""
    left, right = json.loads(current.read_text(encoding="utf-8")), json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("RECOVERY_CANDIDATE_WRONG_JSON_TYPE")
    left_keys, right_keys = set(left), set(right)
    changed = sorted(key for key in left_keys & right_keys if left[key] != right[key])
    def describe(value: Any) -> dict[str, Any]:
        if isinstance(value, dict): return {"type": "object", "key_count": len(value), "keys": sorted(value)[:30]}
        if isinstance(value, list): return {"type": "array", "length": len(value), "id_fields": sorted({key for row in value if isinstance(row, dict) for key in row if key.endswith("_id")})[:20]}
        return {"type": type(value).__name__, "value_sha256": hashlib.sha256(repr(value).encode()).hexdigest()[:16]}
    return {"current_path": str(current.resolve()), "candidate_path": str(candidate.resolve()), "current_sha256": sha256(current), "candidate_sha256": sha256(candidate), "top_level_only_in_current": sorted(left_keys - right_keys), "top_level_only_in_candidate": sorted(right_keys - left_keys), "changed_top_level_fields": {key: {"current": describe(left[key]), "candidate": describe(right[key])} for key in changed}}


def write_semantic_report(current: Path, candidate: Path, artifact_dir: Path) -> Path:
    report = structural_diff(current, candidate)
    target = artifact_dir / "semantic_reports"; target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{hashlib.sha256(str(candidate.resolve()).encode()).hexdigest()[:16]}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only exact-hash candidate inventory")
    parser.add_argument("--root", action="append", required=True, help="Search root; may be repeated")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--blueprint-sha", required=True)
    parser.add_argument("--next-plan-sha", required=True)
    parser.add_argument("--compare", action="append", default=[], metavar="CURRENT=CANDIDATE", help="Write a content-safe structural diff into the evidence directory")
    args = parser.parse_args()
    expected = {"story_blueprint": args.blueprint_sha.upper(), "next_chapter_plan": args.next_plan_sha.upper()}
    artifact = Path(args.artifact_dir).resolve()
    rows = inventory([Path(value).resolve() for value in args.root], expected, excluded_roots=[artifact])
    write_evidence(rows, artifact, expected)
    for value in args.compare:
        current, separator, candidate = value.partition("=")
        if not separator:
            raise SystemExit("--compare requires CURRENT=CANDIDATE")
        write_semantic_report(Path(current), Path(candidate), artifact)
    print(json.dumps({"candidates": len(rows), "exact_matches": sum(row["matches_expected_pretest_sha"] for row in rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
