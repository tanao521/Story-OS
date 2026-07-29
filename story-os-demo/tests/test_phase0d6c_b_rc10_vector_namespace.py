from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import chromadb
import pytest

from core.project_context import get_project_context
from system.vector_client_manager import (
    LEGACY_COLLECTION_NAME,
    NGRAM_COLLECTION_METADATA,
    NGRAM_COLLECTION_NAME,
    VectorClientManager,
    VectorEmbeddingContractMismatch,
    VectorEmbeddingContractMissing,
)


def _manager(context, *, name=NGRAM_COLLECTION_NAME):
    return VectorClientManager(
        client_factory=lambda _: chromadb.PersistentClient(
            path=str(context.data_dir / "chroma")
        ),
        collection_name=name,
    )


def test_versioned_namespace_leaves_metadata_free_legacy_collection_untouched(
    tmp_path: Path,
) -> None:
    context = get_project_context(tmp_path)
    client = chromadb.PersistentClient(path=str(context.data_dir / "chroma"))
    legacy = client.create_collection(
        LEGACY_COLLECTION_NAME,
        embedding_function=None,
    )
    legacy.add(ids=["legacy"], embeddings=[[0.0] * 384])
    before_metadata = legacy.metadata
    before_count = legacy.count()

    manager = _manager(context)
    current = manager.get_collection(context)

    assert current.name == NGRAM_COLLECTION_NAME
    assert current.metadata == NGRAM_COLLECTION_METADATA
    assert legacy.count() == before_count
    assert legacy.metadata == before_metadata
    manager.close_all()


def test_same_and_new_manager_reopen_rebinds_ngram_and_supports_query_and_add(
    tmp_path: Path,
) -> None:
    context = get_project_context(tmp_path)
    manager_a = _manager(context)
    collection = manager_a.get_collection(context)
    collection.add(ids=["one"], documents=["alpha fixture"])

    reopened = manager_a.get_collection(context)
    assert reopened.metadata == NGRAM_COLLECTION_METADATA
    assert len(reopened.query(query_texts=["alpha"], n_results=1)["ids"][0]) == 1
    manager_a.close_all()

    manager_b = _manager(context)
    reopened_b = manager_b.get_collection(context)
    reopened_b.add(ids=["two"], documents=["beta fixture"])
    assert reopened_b.count() == 2
    assert len(reopened_b.query(query_texts=["beta"], n_results=1)["ids"][0]) == 1
    assert type(getattr(reopened_b, "_embedding_function", None)).__name__ != (
        "DefaultEmbeddingFunction"
    )
    manager_b.close_all()


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        (None, VectorEmbeddingContractMissing),
        (
            {
                **NGRAM_COLLECTION_METADATA,
                "embedding_contract": "other",
            },
            VectorEmbeddingContractMismatch,
        ),
    ],
)
def test_versioned_namespace_missing_or_mismatched_metadata_fails_closed(
    tmp_path: Path,
    metadata,
    error,
) -> None:
    context = get_project_context(tmp_path)
    client = chromadb.PersistentClient(path=str(context.data_dir / "chroma"))
    client.create_collection(
        NGRAM_COLLECTION_NAME,
        metadata=metadata,
        embedding_function=None,
    )
    manager = _manager(context)
    with pytest.raises(error):
        manager.get_collection(context)
    manager.close_all()


def test_cold_process_reopen_uses_ngram_without_network_or_model_cache(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    context = get_project_context(project_root)
    manager = _manager(context)
    collection = manager.get_collection(context)
    collection.add(ids=["cold"], documents=["cold process sentinel"])
    manager.close_all()

    cache_root = tmp_path / "empty-cache"
    cache_root.mkdir()
    env = os.environ.copy()
    for key in (
        "HF_HOME",
        "TRANSFORMERS_CACHE",
        "SENTENCE_TRANSFORMERS_HOME",
        "XDG_CACHE_HOME",
    ):
        env[key] = str(cache_root)
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"

    script = textwrap.dedent(
        f"""
        import json, socket
        from pathlib import Path
        import chromadb
        from core.project_context import get_project_context
        from system.vector_client_manager import VectorClientManager

        attempts = []
        original = socket.socket.connect
        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("127."):
                attempts.append(repr(address))
                raise OSError("non-loopback blocked")
            return original(sock, address)
        socket.socket.connect = guarded

        context = get_project_context(Path({str(context.root)!r}))
        manager = VectorClientManager(
            client_factory=lambda _: chromadb.PersistentClient(
                path=str(context.data_dir / "chroma")
            )
        )
        collection = manager.get_collection(context)
        result = collection.query(query_texts=["cold sentinel"], n_results=1)
        print(json.dumps({{
            "ids": result["ids"][0],
            "embedding_type": type(collection._embedding_function).__name__,
            "metadata": collection.metadata,
            "attempts": attempts,
        }}))
        manager.close_all()
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["ids"] == ["cold"]
    assert result["metadata"] == NGRAM_COLLECTION_METADATA
    assert result["embedding_type"] != "DefaultEmbeddingFunction"
    assert result["attempts"] == []
    assert list(cache_root.rglob("*")) == []
