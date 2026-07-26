"""Generate a content-free integrity manifest for a local Chroma directory.

The audit opens Chroma's SQLite catalog in immutable read-only mode. It records
hashes and counts, but never emits document text, metadata values that may hold
story content, or embedding vectors.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
DOCUMENT_KEY = "chroma:document"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _set_hash(values: Iterable[str]) -> str:
    canonical = "\n".join(sorted(set(values))).encode("utf-8")
    return _sha256_bytes(canonical)


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        stat = path.stat()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256_file(path),
            }
        )
    return files


def _tree_hash(files: Iterable[dict[str, Any]]) -> str:
    rows = [
        f"{item['path']}\t{item['size']}\t{item['mtime_ns']}\t{item['sha256']}"
        for item in files
    ]
    return _set_hash(rows)


def _git_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _metadata_value(row: sqlite3.Row) -> Any:
    for key in ("string_value", "int_value", "float_value", "bool_value"):
        if row[key] is not None:
            return bool(row[key]) if key == "bool_value" else row[key]
    return None


def _resolve_source_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _logical_inventory(database: Path, project_root: Path) -> dict[str, Any]:
    uri = f"file:{database.resolve().as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        collections: list[dict[str, Any]] = []
        total_embeddings = 0

        for collection in connection.execute(
            "SELECT id, name, dimension FROM collections ORDER BY name"
        ):
            segment_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM segments WHERE collection = ? AND scope = 'METADATA' "
                    "ORDER BY id",
                    (collection["id"],),
                )
            ]
            records: list[tuple[str, str, dict[str, Any]]] = []
            for segment_id in segment_ids:
                for embedding in connection.execute(
                    "SELECT id, embedding_id FROM embeddings "
                    "WHERE segment_id = ? ORDER BY embedding_id",
                    (segment_id,),
                ):
                    metadata: dict[str, Any] = {}
                    document = ""
                    for row in connection.execute(
                        "SELECT key, string_value, int_value, float_value, bool_value "
                        "FROM embedding_metadata WHERE id = ? ORDER BY key",
                        (embedding["id"],),
                    ):
                        value = _metadata_value(row)
                        if row["key"] == DOCUMENT_KEY:
                            document = str(value or "")
                        else:
                            metadata[row["key"]] = value
                    records.append((embedding["embedding_id"], document, metadata))

            ids = [record[0] for record in records]
            documents = [record[1] for record in records]
            metadata_rows = [
                json.dumps(
                    {"document_id": document_id, "metadata": metadata},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for document_id, _, metadata in records
            ]
            source_types = sorted(
                {str(metadata.get("source_type", "")) for _, _, metadata in records}
            )
            missing_sources = sum(
                1
                for _, _, metadata in records
                if metadata.get("source_path")
                and not _resolve_source_path(
                    project_root, str(metadata["source_path"])
                ).exists()
            )
            project_ids = sorted(
                {str(metadata["project_id"]) for _, _, metadata in records if metadata.get("project_id")}
            )
            timeline_ids = sorted(
                {str(metadata["timeline_id"]) for _, _, metadata in records if metadata.get("timeline_id")}
            )
            canon_revisions = sorted(
                {
                    str(metadata["canon_revision_id"])
                    for _, _, metadata in records
                    if metadata.get("canon_revision_id")
                }
            )
            canon_status_counts: dict[str, int] = {}
            for _, _, metadata in records:
                status = str(metadata.get("canon_status", "legacy_unspecified"))
                canon_status_counts[status] = canon_status_counts.get(status, 0) + 1

            total_embeddings += len(records)
            collections.append(
                {
                    "name": collection["name"],
                    "dimension": collection["dimension"],
                    "record_count": len(records),
                    "document_id_set_hash": _set_hash(ids),
                    "document_content_set_hash": _set_hash(documents),
                    "metadata_normalized_hash": _set_hash(metadata_rows),
                    "source_types": source_types,
                    "project_identities": project_ids,
                    "timeline_identities": timeline_ids,
                    "canon_revision_count": len(canon_revisions),
                    "canon_revision_set_hash": _set_hash(canon_revisions),
                    "canon_status_counts": canon_status_counts,
                    "orphan_source_path_count": missing_sources,
                    "duplicate_document_id_count": len(ids) - len(set(ids)),
                    "duplicate_document_content_count": len(documents) - len(set(documents)),
                }
            )

        return {
            "sqlite_integrity_check": integrity,
            "sqlite_foreign_key_issue_count": foreign_key_issues,
            "collection_count": len(collections),
            "collections": collections,
            "embedding_count": total_embeddings,
        }
    finally:
        connection.close()


def _authority_inventory(project_root: Path) -> dict[str, Any]:
    data = project_root / "data"
    candidates = [
        *sorted((data / "chapters").glob("chapter_*.md")),
        *sorted((data / "summaries").glob("chapter_*_summary.json")),
        data / "characters.json",
        data / "world_bible.json",
    ]
    files = []
    for path in candidates:
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(project_root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    rows = [f"{item['path']}\t{item['size']}\t{item['sha256']}" for item in files]
    return {
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "asset_set_hash": _set_hash(rows),
        "files": files,
    }


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    chroma_dir = args.chroma_dir.resolve()
    project_root = args.project_root.resolve()
    database = chroma_dir / "chroma.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(f"Missing Chroma catalog: {database}")
    files = _file_inventory(chroma_dir)
    try:
        chroma_version = importlib.metadata.version("chromadb")
    except importlib.metadata.PackageNotFoundError:
        chroma_version = "not-installed"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(project_root),
        "python_version": sys.version.split()[0],
        "chroma_version": chroma_version,
        "recovery_path": args.recovery_path,
        "project_identity": args.project_identity,
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "directory_tree_hash": _tree_hash(files),
        "files": files,
        "logical_inventory": _logical_inventory(database, project_root),
        "authority_source_assets": _authority_inventory(project_root),
        "quarantine_path": args.quarantine_path,
        "recovery_summary": args.recovery_summary,
        "historical_evidence_limit": args.historical_evidence_limit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recovery-path", required=True)
    parser.add_argument("--project-identity", required=True)
    parser.add_argument("--quarantine-path", default="")
    parser.add_argument("--recovery-summary", default="")
    parser.add_argument("--historical-evidence-limit", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
                "directory_tree_hash": manifest["directory_tree_hash"],
                "collection_count": manifest["logical_inventory"]["collection_count"],
                "embedding_count": manifest["logical_inventory"]["embedding_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
