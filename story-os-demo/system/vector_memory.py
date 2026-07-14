"""ChromaDB vector memory for StoryOS — semantic retrieval across chapters, summaries,
characters, and world bible.

v0.9 — local vector database with persistent ChromaDB storage.
Uses a pure-Python character‑ngram embedding function so that no model
download is required.  When ``sentence-transformers`` is installed the
module will prefer a multilingual transformer model for higher-quality
embeddings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

# ── lazy imports to keep the module importable without chromadb ──────────────
_chromadb: Any = None
_embedding_fn: Any = None
_COLLECTION_NAME = "storyos_memory"
_EMBEDDING_DIM = 384  # match all-MiniLM-L6-v2 dimension


class _NgramEmbeddingFunction:
    """Pure-Python character‑ngram embedding.

    No model download, no network access, works out of the box for
    Chinese and English text.  Uses character bigrams and trigrams
    hashed into a fixed-dimension sparse vector.
    """

    def __init__(self, dim: int = _EMBEDDING_DIM):
        self._dim = dim

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [_ngram_embed(text, self._dim) for text in input]

    def name(self) -> str:
        return "storyos-ngram-v1"


def _ngram_embed(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Hash character bigrams + trigrams into a *dim*-dimensional vector."""
    vec = [0.0] * dim
    text = text.lower().strip()
    if not text:
        return vec
    # extract bigrams and trigrams (character-level, so CJK works)
    grams: list[str] = []
    chars = list(text)
    for i in range(len(chars) - 1):
        grams.append(chars[i] + chars[i + 1])
    for i in range(len(chars) - 2):
        grams.append(chars[i] + chars[i + 1] + chars[i + 2])
    if not grams:
        grams = [text[:10]]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8", errors="replace")).hexdigest(), 16)
        vec[h % dim] += 1.0
    # L2-normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _ensure_chromadb() -> tuple[Any, Any]:
    """Lazy-import chromadb and resolve the embedding function.

    Returns ``(chromadb_module, embedding_function)``.  If chromadb is not
    installed both values are ``None``.
    """
    global _chromadb, _embedding_fn
    if _chromadb is not None:
        return _chromadb, _embedding_fn

    try:
        import chromadb  # type: ignore[import-untyped]
    except ImportError:
        return None, None

    _chromadb = chromadb
    _embedding_fn = _NgramEmbeddingFunction()
    return _chromadb, _embedding_fn


def _chroma_dir(data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / "chroma"


def _collection(data_dir: str | Path = "data") -> Any | None:
    chromadb_module, _ = _ensure_chromadb()
    if chromadb_module is None:
        return None
    client = chromadb_module.PersistentClient(
        path=str(_chroma_dir(data_dir)),
    )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Could not reconstruct embedding function sentence_transformer.*")
            return client.get_collection(_COLLECTION_NAME)
    except Exception:
        return client.create_collection(name=_COLLECTION_NAME)


# ── public API ────────────────────────────────────────────────────────────────


def build_or_update_index(data_dir: str | Path = "data") -> dict[str, Any]:
    """Build (or update) the ChromaDB vector index for all non-archived chapters,
    summaries, characters, and world bible entries.

    Returns a command-style result dict with ``status``, ``message``, ``outputs``,
    and ``warnings``.
    """
    data = Path(data_dir)
    chromadb_module, _ = _ensure_chromadb()
    if chromadb_module is None:
        return {
            "status": "failed",
            "message": "chromadb 未安装，请运行 pip install chromadb",
            "outputs": {},
            "warnings": [],
        }

    col = _collection(data)
    if col is None:
        return {
            "status": "failed",
            "message": "无法创建或获取 ChromaDB 集合",
            "outputs": {},
            "warnings": [],
        }

    warnings: list[str] = []
    total_chunks = 0
    chapters_indexed = 0

    try:
        # ── 1. index chapter text ──────────────────────────────────────────
        chapters_dir = data / "chapters"
        if chapters_dir.exists():
            for md_path in sorted(chapters_dir.glob("chapter_*.md")):
                chapter_id = _chapter_id_from_path(md_path)
                doc_id = f"chapter_{chapter_id:03d}"
                _safe_delete(col, {"chapter_id": chapter_id}, warnings)

                text = md_path.read_text(encoding="utf-8")
                chunks = _chunk_text(text, chunk_size=500, overlap=100)
                chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "chapter_id": chapter_id,
                        "source_type": "chapter",
                        "source_path": md_path.as_posix(),
                    }
                    for _ in chunks
                ]
                w = _safe_add(col, chunk_ids, chunks, metadatas)
                warnings.extend(w)
                if not w:
                    total_chunks += len(chunks)
                    chapters_indexed += 1

        # ── 2. index summaries ─────────────────────────────────────────────
        summaries_dir = data / "summaries"
        if summaries_dir.exists():
            for json_path in sorted(summaries_dir.glob("chapter_*_summary.json")):
                chapter_id = _chapter_id_from_path(json_path)
                doc_id = f"summary_{chapter_id:03d}"
                try:
                    summary = json.loads(json_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    warnings.append(f"跳过无效 JSON：{json_path.as_posix()}")
                    continue

                snippet = str(summary.get("short_summary", ""))
                tags = " ".join(
                    str(t) for t in summary.get("memory_tags", []) if isinstance(t, str)
                )
                events = " ".join(
                    str(e) for e in summary.get("key_events", []) if isinstance(e, str)
                )
                text = f"摘要: {snippet}\n标签: {tags}\n事件: {events}"
                if not text.strip() or text.strip() in {"摘要: ", "摘要: \n标签: \n事件: "}:
                    continue

                chunks = _chunk_text(text, chunk_size=400, overlap=80)
                chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "chapter_id": chapter_id,
                        "source_type": "summary",
                        "source_path": json_path.as_posix(),
                    }
                    for _ in chunks
                ]
                w = _safe_add(col, chunk_ids, chunks, metadatas)
                warnings.extend(w)
                if not w:
                    total_chunks += len(chunks)

        # ── 3. index characters ────────────────────────────────────────────
        characters_path = data / "characters.json"
        if characters_path.exists():
            _safe_delete(col, {"source_type": "character"}, warnings)
            try:
                chars = json.loads(characters_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                chars = {}
            all_chars = chars.get("main_characters", []) + chars.get(
                "supporting_characters", []
            )
            for char in all_chars:
                if not isinstance(char, dict):
                    continue
                char_id = str(char.get("id", char.get("name", "")))
                doc_id = f"char_{_safe_id(char_id)}"
                text = _character_text(char)
                if not text.strip():
                    continue
                chunks = _chunk_text(text, chunk_size=300, overlap=60)
                chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "source_type": "character",
                        "source_path": characters_path.as_posix(),
                        "character_name": str(char.get("name", "")),
                    }
                    for _ in chunks
                ]
                w = _safe_add(col, chunk_ids, chunks, metadatas)
                warnings.extend(w)
                if not w:
                    total_chunks += len(chunks)

        # ── 4. index world bible ───────────────────────────────────────────
        world_path = data / "world_bible.json"
        if world_path.exists():
            _safe_delete(col, {"source_type": "world_bible"}, warnings)
            try:
                world = json.loads(world_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                world = {}
            rules = [
                r.get("rule", "")
                for r in world.get("core_rules", [])
                if isinstance(r, dict) and r.get("rule")
            ]
            continuity = [
                r
                for r in world.get("continuity_rules", [])
                if isinstance(r, str)
            ]
            locations = [
                loc.get("name", "")
                for loc in world.get("locations", [])
                if isinstance(loc, dict) and loc.get("name")
            ]
            style = str(world.get("world_style", ""))
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
            if text.strip():
                chunks = _chunk_text(text, chunk_size=400, overlap=80)
                chunk_ids = [
                    f"world_bible_chunk_{i}" for i in range(len(chunks))
                ]
                metadatas = [
                    {
                        "source_type": "world_bible",
                        "source_path": world_path.as_posix(),
                    }
                    for _ in chunks
                ]
                w = _safe_add(col, chunk_ids, chunks, metadatas)
                warnings.extend(w)
                if not w:
                    total_chunks += len(chunks)

    except Exception as exc:
        return {
            "status": "failed",
            "message": f"向量索引构建失败：{_error_text(exc)}",
            "outputs": {"chunks_indexed": total_chunks},
            "warnings": warnings,
        }

    # ── write index report ──────────────────────────────────────────────────
    report = {
        "index_version": "0.9",
        "collection_name": _COLLECTION_NAME,
        "chroma_dir": _chroma_dir(data).as_posix(),
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "chunks_indexed": total_chunks,
        "chapters_indexed": chapters_indexed,
        "warnings": warnings,
    }
    report_path = data / "memory" / "vector_index_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # ── update state.json ───────────────────────────────────────────────────
    state_path = data / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
        state["vector_memory"] = {
            "enabled": True,
            "index_version": "0.9",
            "last_indexed_at": report["indexed_at"],
            "chunk_count": total_chunks,
            "collection_name": _COLLECTION_NAME,
        }
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    message = (
        f"向量索引已更新：{chapters_indexed} 章，共 {total_chunks} 个片段。"
        if chapters_indexed
        else f"向量索引已更新，共 {total_chunks} 个片段。"
    )
    return {
        "status": "success",
        "message": message,
        "outputs": {
            "index_path": report_path.as_posix(),
            "chunks_indexed": total_chunks,
            "chapters_indexed": chapters_indexed,
            "collection_name": _COLLECTION_NAME,
        },
        "warnings": warnings,
    }


def search_similar(
    query: str,
    data_dir: str | Path = "data",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Semantic search across the vector index.

    Returns a list of result dicts sorted by relevance (descending).
    Returns an empty list when chromadb is not installed or the index
    hasn't been built yet.
    """
    if not query or not query.strip():
        return []

    data = Path(data_dir)
    col = _collection(data)
    if col is None or col.count() == 0:
        return []

    # Compute embedding ourselves — ChromaDB can't always reconstruct
    # the custom embedding function from serialized config.
    query_embedding = _ngram_embed(query.strip(), _EMBEDDING_DIM)
    try:
        raw = col.query(query_embeddings=[query_embedding], n_results=max_results)
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

        chapter_id = meta.get("chapter_id") if isinstance(meta, dict) else None
        source_type = meta.get("source_type", "") if isinstance(meta, dict) else ""
        source_path = meta.get("source_path", "") if isinstance(meta, dict) else ""

        label = _source_label(doc_id, source_type, meta)
        snippet = str(doc)[:180].replace("\n", " ").strip()

        results.append(
            {
                "type": "vector",
                "chapter_id": int(chapter_id) if chapter_id is not None else 0,
                "path": str(source_path),
                "label": label,
                "score": float(_distance_to_score(distance)),
                "snippet": snippet,
                "matched_fields": [str(source_type)] if source_type else ["vector_memory"],
            }
        )

    return results


def is_available(data_dir: str | Path = "data") -> bool:
    """Return ``True`` when the vector index is built and ready for queries."""
    _, _ = _ensure_chromadb()
    if _chromadb is None:
        return False
    report_path = Path(data_dir) / "memory" / "vector_index_report.json"
    return report_path.exists()


def collection_stats(data_dir: str | Path = "data") -> dict[str, Any]:
    """Return metadata about the current vector collection."""
    data = Path(data_dir)
    report_path = data / "memory" / "vector_index_report.json"
    if not report_path.exists():
        return {"exists": False, "collection_name": _COLLECTION_NAME}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"exists": True, "collection_name": _COLLECTION_NAME}
    return {
        "exists": True,
        "collection_name": report.get("collection_name", _COLLECTION_NAME),
        "index_version": report.get("index_version", ""),
        "indexed_at": report.get("indexed_at", ""),
        "chunks_indexed": report.get("chunks_indexed", 0),
        "chapters_indexed": report.get("chapters_indexed", 0),
        "chroma_dir": report.get("chroma_dir", ""),
    }


# ── internal helpers ─────────────────────────────────────────────────────────


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Split *text* into overlapping chunks, trying to break on paragraph
    or sentence boundaries."""
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
            # carry overlap into next chunk
            carry = current[-overlap:] if len(current) > overlap else ""
            current = f"{carry}\n{para}".strip() if carry else para
    if current:
        chunks.append(current[:chunk_size])
    return chunks if chunks else [text[:chunk_size]]


def _safe_add(
    col: Any, ids: list[str], docs: list[str], metas: list[dict[str, Any]]
) -> list[str]:
    """Add documents to the collection. Return a list of warnings for any
    items that could not be added."""
    warnings: list[str] = []
    if not ids:
        return warnings
    embeddings = [_ngram_embed(doc, _EMBEDDING_DIM) for doc in docs]
    # Check if already indexed
    try:
        existing = col.get(ids=[ids[0]])
        if existing and existing.get("ids"):
            return warnings  # already in collection, not an error
    except Exception:
        pass
    try:
        col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        return warnings
    except Exception as exc:
        first_error = _error_text(exc)
    # Fall back to one-by-one adds
    failed = 0
    for i, doc_id in enumerate(ids):
        try:
            col.add(ids=[doc_id], documents=[docs[i]], metadatas=[metas[i]], embeddings=[embeddings[i]])
        except Exception:
            failed += 1
    if failed:
        warnings.append(
            f"向量添加失败：{failed}/{len(ids)} 条（{first_error[:120]}）"
        )
    return warnings


def _safe_delete(col: Any, where: dict[str, Any], warnings: list[str]) -> None:
    """Drop old source chunks before a local incremental replacement."""
    if not hasattr(col, "delete"):
        return
    try:
        col.delete(where=where)
    except Exception as exc:
        warnings.append(f"Vector cleanup failed: {_error_text(exc)[:120]}")


def _safe_id(raw: str) -> str:
    """Replace characters that ChromaDB may reject in IDs."""
    clean = "".join(
        c if c.isalnum() or c in {"-", "_"} else "_" for c in raw
    )
    return clean or "unknown"


def _chapter_id_from_path(path: Path) -> int:
    """Extract chapter number from filenames like ``chapter_003_draft.json``."""
    import re

    m = re.search(r"chapter_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


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
    """Convert ChromaDB distance to a 0-1 similarity score.

    For cosine distance (0=identical, 1=orthogonal, 2=opposite)
    this maps the range [0, 2] onto [1, 0].
    """
    return max(0.0, min(1.0, 1.0 - distance / 2.0))


def _error_text(exc: Exception) -> str:
    msg = str(exc).strip()
    return msg[:300] if msg else exc.__class__.__name__
