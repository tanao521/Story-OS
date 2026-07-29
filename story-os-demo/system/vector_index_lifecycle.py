"""Vector index lifecycle operations — strict project/timeline/canon isolation."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext

from .vector_client_manager import VectorClientManager
from .vector_index_schema import (
    CanonStatus,
    IndexManifest,
    SourceType,
    VectorMetadata,
    compute_content_hash,
    generate_document_id,
    is_legacy_index,
    load_manifest,
    save_manifest,
    validate_project_match,
    validate_timeline_id,
    VectorScope,
    branch_manifest_path,
    generate_scoped_document_id,
)

_COLLECTION_NAME = "storyos_memory"
_fault_injector = None


def _collection(context: ProjectContext, manager: VectorClientManager | None = None):
    return (manager or VectorClientManager()).get_collection(context)


class VectorIndexLifecycleError(RuntimeError):
    code = "VECTOR_INDEX_ERROR"


class LegacyIndexError(VectorIndexLifecycleError):
    code = "VECTOR_INDEX_LEGACY"


class ProjectMismatchError(VectorIndexLifecycleError):
    code = "VECTOR_INDEX_PROJECT_MISMATCH"


class InvalidTimelineError(VectorIndexLifecycleError):
    code = "VECTOR_INDEX_INVALID_TIMELINE"


class VectorScopeRequired(VectorIndexLifecycleError):
    code = "VECTOR_SCOPE_REQUIRED"


class BranchVectorNotReady(VectorIndexLifecycleError):
    code = "BRANCH_VECTOR_NOT_READY"


class VectorOperationConflict(VectorIndexLifecycleError):
    code = "VECTOR_OPERATION_CONFLICT"


def _scope_where(scope: VectorScope) -> dict[str, Any]:
    return {"$and": [{"project_id": scope.project_id}, {"timeline_id": scope.timeline_id}, {"branch_id": scope.branch_id}, {"canon_revision_id": scope.canon_revision_id}, {"canon_status": "active"}, {"branch_lifecycle_status": "open"}]}


def _fault(point: str) -> None:
    """Test-only recovery seam; production leaves this unset."""
    if _fault_injector is not None:
        _fault_injector(point)


def _manifest_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "record_fingerprint"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _source_manifest_fingerprint(context: ProjectContext) -> str:
    """Fingerprint the rebuild source set before claiming an operation."""
    rows = []
    for path in sorted(context.chapters_dir.glob("chapter_*.md")):
        rows.append({
            "path": path.name,
            "content_fingerprint": compute_content_hash(path.read_text(encoding="utf-8")),
        })
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_verified_manifest(context: ProjectContext, scope: VectorScope) -> dict[str, Any]:
    path = branch_manifest_path(context.data_dir, scope)
    if not path.exists():
        raise BranchVectorNotReady("Branch vector index is not ready")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BranchVectorNotReady("Branch vector manifest is unreadable") from exc
    expected = {
        "project_id": scope.project_id,
        "timeline_id": scope.timeline_id,
        "branch_id": scope.branch_id,
        "canon_revision_id": scope.canon_revision_id,
        "branch_lifecycle_status": "open",
        "vector_ready": True,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise BranchVectorNotReady("Branch vector manifest does not match the requested scope")
    if manifest.get("record_fingerprint") != _manifest_fingerprint(manifest):
        raise BranchVectorNotReady("Branch vector manifest integrity check failed")
    return manifest


def _write_phase(path: Path, request: dict[str, Any], phase: str, **extra: Any) -> None:
    payload = {
        "operation_id": request["operation_id"],
        "operation_type": request["operation_type"],
        "project_id": request["project_id"],
        "timeline_id": request["timeline_id"],
        "branch_id": request["branch_id"],
        "canon_revision_id": request["canon_revision_id"],
        "canonical_request_fingerprint": request["canonical_request_fingerprint"],
        "phase": phase,
        **extra,
    }
    _atomic_manifest(path, payload)


def _verify_phase(phase_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if not phase_path.exists():
        return {}
    try:
        phase = json.loads(phase_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VectorOperationConflict("VECTOR_OPERATION_CONFLICT") from exc
    keys = ("operation_id", "operation_type", "project_id", "timeline_id", "branch_id", "canon_revision_id", "canonical_request_fingerprint")
    if any(phase.get(key) != request.get(key) for key in keys):
        raise VectorOperationConflict("VECTOR_OPERATION_CONFLICT")
    return phase


def _assert_scope(context: ProjectContext, scope: VectorScope, *, business: bool) -> None:
    if not isinstance(scope, VectorScope) or scope.project_id != _project_id_from_context(context):
        raise VectorScopeRequired("Complete matching VectorScope is required")
    from core.contracts.narrative_turn import BranchLifecycleStatus, TimelineContext
    from system.narrative_branch_store import NarrativeBranchStore
    timeline = TimelineContext(project_id=scope.project_id, timeline_id=scope.timeline_id)
    store = NarrativeBranchStore(context)
    branch = store.get_branch(timeline, scope.branch_id)
    if branch is None:
        raise VectorScopeRequired("Branch not found")
    if branch.lifecycle_status != BranchLifecycleStatus.OPEN:
        raise VectorScopeRequired("Branch is archived")
    if business and store.get_active_branch_id(timeline) != scope.branch_id:
        raise VectorScopeRequired("Branch is inactive")


def _atomic_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except OSError: pass


def index_scoped_records(context: ProjectContext, scope: VectorScope, records: list[dict[str, Any]], *, operation_id: str, vector_client_manager: VectorClientManager | None = None) -> dict[str, Any]:
    """Sole E3 branch-aware write entrypoint."""
    _assert_scope(context, scope, business=False)
    col = _collection(context) if vector_client_manager is None else _collection(context, vector_client_manager)
    if col is None:
        return {"status": "failed", "code": "VECTOR_INTERNAL_ERROR"}
    ids, docs, metas = [], [], []
    for record in records:
        text = str(record.get("text", "")); source_type = SourceType(str(record.get("source_type", "chapter")))
        source_identity = str(record.get("source_identity", record.get("chapter_id", "source")))
        source_fingerprint = compute_content_hash(text)
        doc_id = generate_scoped_document_id(scope, source_type, source_identity, int(record.get("chunk_index", 0)), source_fingerprint)
        meta = {"schema_version": 3, "project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "canon_revision_id": scope.canon_revision_id, "canon_status": "active", "branch_lifecycle_status": "open", "source_type": source_type.value, "source_identity": source_identity, "chapter_id": int(record.get("chapter_id", 0)), "source_version_id": str(record.get("source_version_id", "")), "source_fingerprint": source_fingerprint, "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        meta["record_fingerprint"] = hashlib.sha256(json.dumps(meta, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        ids.append(doc_id); docs.append(text); metas.append(meta)
    _safe_delete(col, {"project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "canon_revision_id": scope.canon_revision_id})
    _safe_add(col, ids, docs, metas)
    manifest = {"schema_version": 3, "project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "canon_revision_id": scope.canon_revision_id, "branch_lifecycle_status": "open", "vector_ready": True, "record_count": len(ids), "source_fingerprints": sorted(meta["source_fingerprint"] for meta in metas), "index_revision": hashlib.sha256("".join(ids).encode()).hexdigest(), "last_completed_operation_id": operation_id}
    manifest["record_fingerprint"] = _manifest_fingerprint(manifest)
    _atomic_manifest(branch_manifest_path(context.data_dir, scope), manifest)
    return {"status": "success", "record_count": len(ids), "manifest": manifest}


def search_scoped(context: ProjectContext, scope: VectorScope, query: str, *, max_results: int = 5, business: bool = True) -> list[dict[str, Any]]:
    _assert_scope(context, scope, business=business)
    _load_verified_manifest(context, scope)
    col = _collection(context)
    if col is None:
        raise BranchVectorNotReady("Vector client unavailable")
    raw = col.query(query_texts=[query], n_results=max_results, where=_scope_where(scope), include=["documents", "metadatas", "distances"])
    out = []
    ids = (raw.get("ids") or [[]])[0]; docs = (raw.get("documents") or [[]])[0]; metas = (raw.get("metadatas") or [[]])[0]
    for index, doc_id in enumerate(ids):
        meta = metas[index] if index < len(metas) else {}
        if any(meta.get(key) != value for key, value in (("project_id", scope.project_id), ("timeline_id", scope.timeline_id), ("branch_id", scope.branch_id), ("canon_revision_id", scope.canon_revision_id), ("canon_status", "active"), ("branch_lifecycle_status", "open"))):
            continue
        out.append({"id": doc_id, "text": docs[index] if index < len(docs) else "", "metadata": meta})
    return out


def archive_branch_index(context: ProjectContext, scope: VectorScope, *, vector_client_manager: VectorClientManager | None = None) -> dict[str, Any]:
    col = _collection(context) if vector_client_manager is None else _collection(context, vector_client_manager)
    if col is not None:
        _safe_delete(col, {"project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id})
    path = branch_manifest_path(context.data_dir, scope)
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8")); manifest["branch_lifecycle_status"] = "archived"; manifest["vector_ready"] = False; manifest["record_fingerprint"] = _manifest_fingerprint(manifest); _atomic_manifest(path, manifest)
    return {"status": "success", "vector_ready": False}


def sync_branch_index(context: ProjectContext, scope: VectorScope, *, operation_id: str, operation_type: str, vector_client_manager: VectorClientManager | None = None) -> dict[str, Any]:
    """Recoverable archive/rebuild/restore vector synchronization authority."""
    if operation_type not in {"archive", "restore", "rebuild", "repair"}:
        raise VectorScopeRequired("Invalid vector operation type")
    if not operation_id or Path(operation_id).name != operation_id or operation_id in {".", ".."}:
        raise VectorScopeRequired("Invalid operation_id")
    operations = context.data_dir / "chroma" / "operations"
    authority_path = operations / f"{operation_id}.json"; phase_path = operations / f"{operation_id}.phase.json"
    request = {"operation_id": operation_id, "operation_type": operation_type, "project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "canon_revision_id": scope.canon_revision_id, "source_manifest_fingerprint": _source_manifest_fingerprint(context)}
    request["canonical_request_fingerprint"] = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if authority_path.exists():
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        if authority.get("canonical_request_fingerprint") != request["canonical_request_fingerprint"]:
            raise VectorOperationConflict("VECTOR_OPERATION_CONFLICT")
        phase = _verify_phase(phase_path, request)
        if phase.get("phase") == "COMPLETED":
            return {"status": "success", "idempotent_replay": True, "vector_ready": operation_type != "archive"}
    else:
        request["created_at"] = datetime.now(timezone.utc).isoformat(); request["record_fingerprint"] = _manifest_fingerprint(request); _atomic_manifest(authority_path, request)
    _write_phase(phase_path, request, "OPERATION_CLAIMED")
    _fault("after_authority_claim")
    if operation_type == "archive":
        result = archive_branch_index(context, scope, vector_client_manager=vector_client_manager)
    else:
        _assert_scope(context, scope, business=False)
        records=[]
        for path in sorted(context.chapters_dir.glob("chapter_*.md")):
            chapter_id=int(path.stem.split("_")[-1]); records.append({"source_type":"chapter","chapter_id":chapter_id,"source_identity":str(chapter_id),"source_version_id":scope.canon_revision_id,"text":path.read_text(encoding="utf-8")})
        _write_phase(phase_path, request, "SOURCE_SCANNED", source_manifest_fingerprint=request["source_manifest_fingerprint"])
        _fault("after_source_scan")
        _write_phase(phase_path, request, "OLD_SCOPE_MARKED_STALE")
        _fault("after_old_scope_marked_stale")
        result=index_scoped_records(context, scope, records, operation_id=operation_id, vector_client_manager=vector_client_manager)
        _fault("after_first_record_batch")
        _fault("after_all_records_indexed")
        _write_phase(phase_path, request, "MANIFEST_PUBLISHED")
        _fault("after_manifest_publication")
        _load_verified_manifest(context, scope)
        _fault("after_verification")
        result["vector_ready"]=result.get("status")=="success"
    _fault("before_completed_marker")
    _write_phase(phase_path, request, "COMPLETED", vector_ready=result.get("vector_ready", False))
    return {**result, "idempotent_replay": False}


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) <= chunk_size:
            current = f"{current}\n{para}".strip() if current else para
        else:
            if current:
                chunks.append(current[:chunk_size])
            carry = current[-overlap:] if len(current) > overlap else ""
            current = f"{carry}\n{para}".strip() if carry else para
    if current:
        chunks.append(current[:chunk_size])
    return chunks if chunks else [text[:chunk_size]]


def _project_id_from_context(context: ProjectContext) -> str:
    return context.root.name or "default"


def _get_manifest_warnings(context: ProjectContext, timeline_id: str) -> list[str]:
    warnings: list[str] = []
    data_dir = context.data_dir
    
    manifest = load_manifest(data_dir, timeline_id)
    
    if manifest is None:
        main_manifest = load_manifest(data_dir, "main")
        
        if main_manifest is not None and main_manifest.schema_version >= 2:
            from .vector_index_schema import IndexManifest
            new_manifest = IndexManifest(
                schema_version=2,
                project_id=_project_id_from_context(context),
                timeline_id=timeline_id,
                last_rebuilt_at=None,
                document_count=0,
            )
            save_manifest(data_dir, new_manifest, timeline_id)
            return warnings
        
        if main_manifest is not None and main_manifest.schema_version < 2:
            if timeline_id != "main":
                raise LegacyIndexError("Legacy index requires rebuild for non-main timeline.")
            if _project_id_from_context(context) == "story-os-demo":
                warnings.append("Legacy index detected; operating in compatibility mode.")
                return warnings
            raise LegacyIndexError("Legacy index requires rebuild for managed project.")
        
        col = _collection(context)
        if col is not None and col.count() == 0:
            from .vector_index_schema import IndexManifest
            new_manifest = IndexManifest(
                schema_version=2,
                project_id=_project_id_from_context(context),
                timeline_id=timeline_id,
                last_rebuilt_at=None,
                document_count=0,
            )
            save_manifest(data_dir, new_manifest, timeline_id)
            return warnings
        
        if timeline_id == "main" and _project_id_from_context(context) == "story-os-demo":
            warnings.append("Legacy index detected; operating in compatibility mode.")
            return warnings
        else:
            raise LegacyIndexError("Legacy index requires rebuild for non-main timeline or managed project.")
    
    if manifest.schema_version < 2:
        if timeline_id == "main" and _project_id_from_context(context) == "story-os-demo":
            warnings.append("Legacy index detected; operating in compatibility mode.")
            return warnings
        else:
            raise LegacyIndexError("Legacy index requires rebuild for non-main timeline or managed project.")
    
    if not validate_project_match(
        _project_id_from_context(context), manifest.project_id
    ):
        raise ProjectMismatchError(
            f"Project ID mismatch: context={_project_id_from_context(context)}, manifest={manifest.project_id}"
        )
    
    return warnings


def index_chapter(
    context: ProjectContext,
    chapter_id: int,
    chapter_text: str,
    canon_revision_id: str | None = None,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    warnings = _get_manifest_warnings(context, timeline_id)
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {
            "status": "failed",
            "message": "chromadb not available",
            "warnings": warnings,
        }

    chapter_path = context.chapters_dir / f"chapter_{chapter_id:03d}.md"
    content_hash = compute_content_hash(chapter_text)
    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _delete_by_chapter(col, project_id, timeline_id, chapter_id)

    chunks = _chunk_text(chapter_text, chunk_size=500, overlap=100)
    if not chunks:
        return {"status": "success", "message": "No content to index", "warnings": warnings}

    chunk_ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    documents: list[str] = []

    for i, chunk in enumerate(chunks):
        doc_id = generate_document_id(
            project_id, timeline_id, SourceType.CHAPTER, str(chapter_id), i, content_hash
        )
        chunk_ids.append(doc_id)
        documents.append(chunk)
        meta = VectorMetadata(
            project_id=project_id,
            timeline_id=timeline_id,
            source_type=SourceType.CHAPTER,
            source_path=chapter_path.as_posix(),
            chapter_id=chapter_id,
            canon_status=CanonStatus.ACTIVE,
            canon_revision_id=canon_revision_id,
            content_hash=content_hash,
            indexed_at=indexed_at,
        )
        metadatas.append(meta.to_dict())

    _safe_add(col, chunk_ids, documents, metadatas)
    _update_manifest(context, timeline_id, col.count())

    return {
        "status": "success",
        "message": f"Chapter {chapter_id} indexed ({len(chunks)} chunks)",
        "warnings": warnings,
        "outputs": {"chunks_indexed": len(chunks), "content_hash": content_hash},
    }


def index_summary(
    context: ProjectContext,
    chapter_id: int,
    summary_text: str,
    canon_revision_id: str | None = None,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    warnings = _get_manifest_warnings(context, timeline_id)
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {
            "status": "failed",
            "message": "chromadb not available",
            "warnings": warnings,
        }

    summary_path = context.summaries_dir / f"chapter_{chapter_id:03d}_summary.json"
    content_hash = compute_content_hash(summary_text)
    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _delete_by_summary(col, project_id, timeline_id, chapter_id)

    chunks = _chunk_text(summary_text, chunk_size=400, overlap=80)
    if not chunks:
        return {"status": "success", "message": "No content to index", "warnings": warnings}

    chunk_ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    documents: list[str] = []

    for i, chunk in enumerate(chunks):
        doc_id = generate_document_id(
            project_id, timeline_id, SourceType.SUMMARY, str(chapter_id), i, content_hash
        )
        chunk_ids.append(doc_id)
        documents.append(chunk)
        meta = VectorMetadata(
            project_id=project_id,
            timeline_id=timeline_id,
            source_type=SourceType.SUMMARY,
            source_path=summary_path.as_posix(),
            chapter_id=chapter_id,
            canon_status=CanonStatus.ACTIVE,
            canon_revision_id=canon_revision_id,
            content_hash=content_hash,
            indexed_at=indexed_at,
        )
        metadatas.append(meta.to_dict())

    _safe_add(col, chunk_ids, documents, metadatas)
    _update_manifest(context, timeline_id, col.count())

    return {
        "status": "success",
        "message": f"Summary {chapter_id} indexed ({len(chunks)} chunks)",
        "warnings": warnings,
        "outputs": {"chunks_indexed": len(chunks), "content_hash": content_hash},
    }


def index_characters(
    context: ProjectContext,
    characters_data: dict[str, Any],
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    warnings = _get_manifest_warnings(context, timeline_id)
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {
            "status": "failed",
            "message": "chromadb not available",
            "warnings": warnings,
        }

    characters_path = context.data_dir / "characters.json"
    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _delete_by_source_type(col, project_id, timeline_id, SourceType.CHARACTER)

    all_chars = characters_data.get("main_characters", []) + characters_data.get(
        "supporting_characters", []
    )
    if not all_chars:
        return {"status": "success", "message": "No characters to index", "warnings": warnings}

    chunk_ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    documents: list[str] = []

    for char in all_chars:
        if not isinstance(char, dict):
            continue
        char_name = str(char.get("name", ""))
        if not char_name:
            continue
        text = _character_text(char)
        if not text.strip():
            continue
        content_hash = compute_content_hash(text)
        chunks = _chunk_text(text, chunk_size=300, overlap=60)
        for i, chunk in enumerate(chunks):
            doc_id = generate_document_id(
                project_id, timeline_id, SourceType.CHARACTER, char_name, i, content_hash
            )
            chunk_ids.append(doc_id)
            documents.append(chunk)
            meta = VectorMetadata(
                project_id=project_id,
                timeline_id=timeline_id,
                source_type=SourceType.CHARACTER,
                source_path=characters_path.as_posix(),
                character_name=char_name,
                canon_status=CanonStatus.ACTIVE,
                content_hash=content_hash,
                indexed_at=indexed_at,
            )
            metadatas.append(meta.to_dict())

    if chunk_ids:
        _safe_add(col, chunk_ids, documents, metadatas)
        _update_manifest(context, timeline_id, col.count())

    return {
        "status": "success",
        "message": f"Characters indexed ({len(chunk_ids)} chunks)",
        "warnings": warnings,
        "outputs": {"chunks_indexed": len(chunk_ids)},
    }


def index_world_bible(
    context: ProjectContext,
    world_data: dict[str, Any],
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    warnings = _get_manifest_warnings(context, timeline_id)
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {
            "status": "failed",
            "message": "chromadb not available",
            "warnings": warnings,
        }

    world_path = context.data_dir / "world_bible.json"
    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _delete_by_source_type(col, project_id, timeline_id, SourceType.WORLD_BIBLE)

    rules = [
        r.get("rule", "")
        for r in world_data.get("core_rules", [])
        if isinstance(r, dict) and r.get("rule")
    ]
    continuity = [
        r for r in world_data.get("continuity_rules", []) if isinstance(r, str)
    ]
    locations = [
        loc.get("name", "")
        for loc in world_data.get("locations", [])
        if isinstance(loc, dict) and loc.get("name")
    ]
    style = str(world_data.get("world_style", ""))
    parts = []
    if style:
        parts.append(f"世界观风格: {style}")
    if rules:
        parts.append("核心规则:\n" + "\n".join(f"- {r}" for r in rules))
    if continuity:
        parts.append("连续性规则:\n" + "\n".join(f"- {r}" for r in continuity))
    if locations:
        parts.append("重要地点:\n" + "\n".join(f"- {l}" for l in locations))
    text = "\n\n".join(parts)
    if not text.strip():
        return {"status": "success", "message": "No world bible content to index", "warnings": warnings}

    content_hash = compute_content_hash(text)
    chunks = _chunk_text(text, chunk_size=400, overlap=80)

    chunk_ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    documents: list[str] = []

    for i, chunk in enumerate(chunks):
        doc_id = generate_document_id(
            project_id, timeline_id, SourceType.WORLD_BIBLE, "world", i, content_hash
        )
        chunk_ids.append(doc_id)
        documents.append(chunk)
        meta = VectorMetadata(
            project_id=project_id,
            timeline_id=timeline_id,
            source_type=SourceType.WORLD_BIBLE,
            source_path=world_path.as_posix(),
            canon_status=CanonStatus.ACTIVE,
            content_hash=content_hash,
            indexed_at=indexed_at,
        )
        metadatas.append(meta.to_dict())

    _safe_add(col, chunk_ids, documents, metadatas)
    _update_manifest(context, timeline_id, col.count())

    return {
        "status": "success",
        "message": f"World bible indexed ({len(chunks)} chunks)",
        "warnings": warnings,
        "outputs": {"chunks_indexed": len(chunks), "content_hash": content_hash},
    }


_MIN_SCORE_THRESHOLD = 0.45


def search_similar(
    context: ProjectContext,
    query: str,
    timeline_id: str = "main",
    max_results: int = 5,
    source_type: SourceType | None = None,
    exclude_chapter_id: int | None = None,
) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None or col.count() == 0:
        return []

    is_legacy = is_legacy_index(data_dir)
    if is_legacy and timeline_id != "main":
        return []

    try:
        raw = col.query(
            query_texts=[query.strip()],
            n_results=max_results * 3,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    if not raw or not raw.get("ids") or not raw["ids"][0]:
        return []

    results: list[dict[str, Any]] = []
    ids_list = raw["ids"][0]
    docs_list = raw.get("documents", [[]])[0]
    metas_list = raw.get("metadatas", [[]])[0]
    distances_list = raw.get("distances", [[]])[0]

    for i, doc_id in enumerate(ids_list):
        doc = docs_list[i] if i < len(docs_list) else ""
        meta = metas_list[i] if i < len(metas_list) else {}
        distance = distances_list[i] if i < len(distances_list) else 1.0
        score = _distance_to_score(distance)

        if score < _MIN_SCORE_THRESHOLD:
            continue

        if not is_legacy:
            if (
                meta.get("project_id") != project_id
                or meta.get("timeline_id") != timeline_id
                or meta.get("canon_status") != CanonStatus.ACTIVE.value
            ):
                continue
            if source_type and meta.get("source_type") != source_type.value:
                continue
            if exclude_chapter_id is not None and meta.get("chapter_id") == exclude_chapter_id:
                continue

        chapter_id = meta.get("chapter_id") if isinstance(meta, dict) else None
        source_type_val = meta.get("source_type", "") if isinstance(meta, dict) else ""
        source_path = meta.get("source_path", "") if isinstance(meta, dict) else ""

        label = _source_label(doc_id, source_type_val, meta)
        snippet = str(doc)[:180].replace("\n", " ").strip()

        results.append(
            {
                "type": "vector",
                "chapter_id": int(chapter_id) if chapter_id is not None else 0,
                "path": str(source_path),
                "label": label,
                "score": float(score),
                "snippet": snippet,
                "matched_fields": [str(source_type_val)] if source_type_val else ["vector_memory"],
                "metadata": meta if isinstance(meta, dict) else {},
            }
        )

    return results[:max_results]


def delete_by_chapter(
    context: ProjectContext,
    chapter_id: int,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    _delete_by_chapter(col, project_id, timeline_id, chapter_id)
    _update_manifest(context, timeline_id, col.count())

    return {"status": "success", "message": f"Chapter {chapter_id} deleted from index"}


def delete_by_revision(
    context: ProjectContext,
    canon_revision_id: str,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    _delete_by_revision(col, project_id, timeline_id, canon_revision_id)
    _update_manifest(context, timeline_id, col.count())

    return {"status": "success", "message": f"Revision {canon_revision_id} deleted from index"}


def delete_by_timeline(
    context: ProjectContext,
    timeline_id: str,
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    where = {"project_id": project_id, "timeline_id": timeline_id}
    _safe_delete(col, where)
    _update_manifest(context, timeline_id, col.count())

    return {"status": "success", "message": f"Timeline {timeline_id} deleted from index"}


def delete_by_project(context: ProjectContext) -> dict[str, Any]:
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    where = {"project_id": project_id}
    _safe_delete(col, where)
    _update_manifest(context, "main", col.count())

    return {"status": "success", "message": f"Project {project_id} deleted from index"}


def mark_chapter_stale(
    context: ProjectContext,
    chapter_id: int,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    _mark_stale(col, project_id, timeline_id, chapter_id)
    _update_manifest(context, timeline_id, col.count())

    return {"status": "success", "message": f"Chapter {chapter_id} marked stale"}


def mark_chapter_archived(
    context: ProjectContext,
    chapter_id: int,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {"status": "success", "message": "chromadb not available"}

    _mark_archived(col, project_id, timeline_id, chapter_id)
    _update_manifest(context, timeline_id, col.count())

    return {"status": "success", "message": f"Chapter {chapter_id} marked archived"}


def rebuild_project_index(
    context: ProjectContext,
    timeline_id: str = "main",
) -> dict[str, Any]:
    if not validate_timeline_id(timeline_id):
        raise InvalidTimelineError(f"Invalid timeline_id: {timeline_id}")

    warnings: list[str] = []
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    col = _collection(context)
    if col is None:
        return {
            "status": "failed",
            "message": "chromadb not available",
            "warnings": warnings,
        }

    _delete_by_timeline(col, project_id, timeline_id)

    total_chunks = 0

    chapters_dir = context.chapters_dir
    if chapters_dir.exists():
        for md_path in sorted(chapters_dir.glob("chapter_*.md")):
            m = __import__("re").search(r"chapter_(\d+)", md_path.stem)
            if not m:
                continue
            chapter_id = int(m.group(1))
            text = md_path.read_text(encoding="utf-8")
            result = index_chapter(context, chapter_id, text, timeline_id=timeline_id)
            if result["status"] == "success":
                total_chunks += result.get("outputs", {}).get("chunks_indexed", 0)
            warnings.extend(result.get("warnings", []))

    summaries_dir = context.summaries_dir
    if summaries_dir.exists():
        for json_path in sorted(summaries_dir.glob("chapter_*_summary.json")):
            m = __import__("re").search(r"chapter_(\d+)", json_path.stem)
            if not m:
                continue
            chapter_id = int(m.group(1))
            try:
                summary = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            snippet = str(summary.get("short_summary", ""))
            tags = " ".join(
                str(t)
                for t in summary.get("memory_tags", [])
                if isinstance(t, str)
            )
            events = " ".join(
                str(e)
                for e in summary.get("key_events", [])
                if isinstance(e, str)
            )
            text = f"摘要: {snippet}\n标签: {tags}\n事件: {events}"
            if text.strip() and text.strip() not in {"摘要: ", "摘要: \n标签: \n事件: "}:
                result = index_summary(context, chapter_id, text, timeline_id=timeline_id)
                if result["status"] == "success":
                    total_chunks += result.get("outputs", {}).get("chunks_indexed", 0)
                warnings.extend(result.get("warnings", []))

    characters_path = context.data_dir / "characters.json"
    if characters_path.exists():
        try:
            chars = json.loads(characters_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            chars = {}
        result = index_characters(context, chars, timeline_id=timeline_id)
        if result["status"] == "success":
            total_chunks += result.get("outputs", {}).get("chunks_indexed", 0)
        warnings.extend(result.get("warnings", []))

    world_path = context.data_dir / "world_bible.json"
    if world_path.exists():
        try:
            world = json.loads(world_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            world = {}
        result = index_world_bible(context, world, timeline_id=timeline_id)
        if result["status"] == "success":
            total_chunks += result.get("outputs", {}).get("chunks_indexed", 0)
        warnings.extend(result.get("warnings", []))

    _update_manifest(context, timeline_id, col.count())

    return {
        "status": "success",
        "message": f"Project index rebuilt ({total_chunks} chunks)",
        "warnings": warnings,
        "outputs": {"chunks_indexed": total_chunks, "document_count": col.count()},
    }


def collection_stats(context: ProjectContext) -> dict[str, Any]:
    project_id = _project_id_from_context(context)
    data_dir = context.data_dir
    manifest = load_manifest(data_dir)

    result: dict[str, Any] = {
        "project_id": project_id,
        "exists": False,
        "collection_name": _COLLECTION_NAME,
        "is_legacy": is_legacy_index(data_dir),
    }

    col = _collection(context)
    if col is not None:
        result["exists"] = True
        result["document_count"] = col.count()

    if manifest:
        result["schema_version"] = manifest.schema_version
        result["manifest_project_id"] = manifest.project_id
        result["timeline_id"] = manifest.timeline_id
        result["last_rebuilt_at"] = manifest.last_rebuilt_at
        result["warnings"] = manifest.warnings

    return result


def _delete_by_chapter(col, project_id: str, timeline_id: str, chapter_id: int):
    where = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "source_type": SourceType.CHAPTER.value,
        "chapter_id": chapter_id,
    }
    _safe_delete(col, where)
    where_summary = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "source_type": SourceType.SUMMARY.value,
        "chapter_id": chapter_id,
    }
    _safe_delete(col, where_summary)


def _delete_by_summary(col, project_id: str, timeline_id: str, chapter_id: int):
    where = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "source_type": SourceType.SUMMARY.value,
        "chapter_id": chapter_id,
    }
    _safe_delete(col, where)


def _delete_by_source_type(col, project_id: str, timeline_id: str, source_type: SourceType):
    where = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "source_type": source_type.value,
    }
    _safe_delete(col, where)


def _delete_by_revision(col, project_id: str, timeline_id: str, canon_revision_id: str):
    where = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "canon_revision_id": canon_revision_id,
    }
    _safe_delete(col, where)


def _delete_by_timeline(col, project_id: str, timeline_id: str):
    where = {"project_id": project_id, "timeline_id": timeline_id}
    _safe_delete(col, where)


def _mark_stale(col, project_id: str, timeline_id: str, chapter_id: int):
    try:
        for source_type_val in [SourceType.CHAPTER.value, SourceType.SUMMARY.value]:
            where = {
                "project_id": project_id,
                "timeline_id": timeline_id,
                "source_type": source_type_val,
                "chapter_id": chapter_id,
            }
            _safe_delete(col, where)
    except Exception:
        pass


def _mark_archived(col, project_id: str, timeline_id: str, chapter_id: int):
    try:
        for source_type_val in [SourceType.CHAPTER.value, SourceType.SUMMARY.value]:
            where = {
                "project_id": project_id,
                "timeline_id": timeline_id,
                "source_type": source_type_val,
                "chapter_id": chapter_id,
            }
            _safe_delete(col, where)
    except Exception:
        pass


def _safe_add(col, ids: list[str], docs: list[str], metas: list[dict[str, Any]]):
    if not ids:
        return
    try:
        col.add(ids=ids, documents=docs, metadatas=metas)
    except Exception:
        for i, doc_id in enumerate(ids):
            try:
                col.add(
                    ids=[doc_id],
                    documents=[docs[i]],
                    metadatas=[metas[i]],
                )
            except Exception:
                pass


def _safe_delete(col, where: dict[str, Any]):
    if not hasattr(col, "delete"):
        return
    try:
        if len(where) > 1:
            where_clause = {"$and": [{k: v} for k, v in where.items()]}
        else:
            where_clause = where
        col.delete(where=where_clause)
    except Exception:
        pass


def _update_manifest(context: ProjectContext, timeline_id: str, document_count: int):
    project_id = _project_id_from_context(context)
    manifest = load_manifest(context.data_dir) or IndexManifest()
    updated = IndexManifest(
        schema_version=2,
        project_id=project_id,
        timeline_id=timeline_id,
        last_rebuilt_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        document_count=document_count,
        warnings=manifest.warnings,
    )
    save_manifest(context.data_dir, updated)


def _source_label(doc_id: str, source_type: str, meta: dict[str, Any]) -> str:
    if source_type == "chapter":
        return f"chapter_text:{doc_id}"
    if source_type == "summary":
        return f"chapter_summary:{doc_id}"
    if source_type == "character":
        name = meta.get("character_name", "") if isinstance(meta, dict) else ""
        return f"character:{name}" if name else f"character:{doc_id}"
    if source_type == "world_bible":
        return "world_bible"
    return f"vector_memory:{doc_id}"


def _distance_to_score(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - distance / 2.0))


def _character_text(char: dict[str, Any]) -> str:
    parts = [f"角色: {char.get('name', '')}"]
    if char.get("role"):
        parts.append(f"定位: {char['role']}")
    if char.get("core_desire"):
        parts.append(f"欲望: {char['core_desire']}")
    if char.get("core_fear"):
        parts.append(f"恐惧: {char['core_fear']}")
    personality = char.get("personality", [])
    if isinstance(personality, list):
        parts.append(f"性格: {' '.join(str(p) for p in personality)}")
    state = char.get("current_state", {})
    if isinstance(state, dict):
        if state.get("physical"):
            parts.append(f"身体: {state['physical']}")
        if state.get("mental"):
            parts.append(f"心理: {state['mental']}")
    voice = char.get("voice_profile", {})
    if isinstance(voice, dict) and voice.get("tone"):
        parts.append(f"语气: {voice['tone']}")
    relationships = char.get("relationships", {})
    if isinstance(relationships, dict) and relationships:
        rel_str = " ".join(
            f"{k}: {v}" for k, v in relationships.items() if isinstance(v, str)
        )
        parts.append(f"关系: {rel_str}")
    return "\n".join(parts)
