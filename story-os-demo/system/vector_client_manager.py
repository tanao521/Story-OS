"""Vector Client Manager - Unified Chroma client lifecycle management.

This module provides a singleton manager for Chroma PersistentClient instances,
ensuring:
- Client reuse within the same process for the same Chroma directory
- Deterministic resource release
- Thread-safe access
- Clean shutdown
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.project_context import ProjectContext


LEGACY_COLLECTION_NAME = "storyos_memory"
NGRAM_COLLECTION_NAME = "storyos_memory_ngram_v1"
NGRAM_EMBEDDING_CONTRACT = "storyos_repository_ngram"
NGRAM_EMBEDDING_VERSION = 1
NGRAM_EMBEDDING_DIMENSION = 512
NGRAM_COLLECTION_METADATA = {
    "embedding_contract": NGRAM_EMBEDDING_CONTRACT,
    "embedding_version": NGRAM_EMBEDDING_VERSION,
    "embedding_dimension": NGRAM_EMBEDDING_DIMENSION,
}


class VectorEmbeddingContractError(RuntimeError):
    pass


class VectorEmbeddingContractMissing(VectorEmbeddingContractError):
    pass


class VectorEmbeddingContractMismatch(VectorEmbeddingContractError):
    pass


class VectorEmbeddingVersionMismatch(VectorEmbeddingContractError):
    pass


class VectorEmbeddingDimensionMismatch(VectorEmbeddingContractError):
    pass


class VectorClientManager:
    _instance: Optional[VectorClientManager] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(
        cls,
        *,
        client_factory: Callable[[ProjectContext], Any] | None = None,
        collection_name: str = NGRAM_COLLECTION_NAME,
    ) -> VectorClientManager:
        if client_factory is not None:
            instance = super().__new__(cls)
            instance._clients = {}
            instance._client_lock = threading.RLock()
            instance._chromadb_module = None
            instance._embedding_fn = None
            instance._client_factory = client_factory
            instance._collection_name = collection_name
            return instance
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._clients: Dict[str, Any] = {}
                cls._instance._client_lock = threading.RLock()
                cls._instance._chromadb_module = None
                cls._instance._embedding_fn = None
                cls._instance._client_factory = None
                cls._instance._collection_name = NGRAM_COLLECTION_NAME
        return cls._instance
    
    def _ensure_chromadb(self) -> tuple[Any, Any]:
        if self._chromadb_module is not None and self._embedding_fn is not None:
            return self._chromadb_module, self._embedding_fn
        
        try:
            import chromadb
        except ImportError:
            return None, None
        
        self._chromadb_module = chromadb
        
        class _NgramEmbeddingFunction:
            def __init__(self):
                self._dim = NGRAM_EMBEDDING_DIMENSION

            def name(self):
                return NGRAM_EMBEDDING_CONTRACT
            
            def __call__(self, input):
                if isinstance(input, list):
                    return [self._embed(text) for text in input]
                return self._embed(input)
            
            def embed_documents(self, texts):
                if isinstance(texts, str):
                    texts = [texts]
                return [self._embed(text) for text in texts]
            
            def embed_query(self, input):
                if isinstance(input, list):
                    return [self._embed(text) for text in input]
                return self._embed(input)
            
            def _embed(self, text):
                import hashlib
                vec = [0.0] * self._dim
                text = text.lower().strip()
                if not text:
                    return vec
                
                grams = []
                import re
                words = re.findall(r'[\w]+', text)
                for word in words:
                    chars = list(word)
                    for i in range(len(chars)):
                        for n in range(2, min(5, len(chars) - i + 1)):
                            grams.append(''.join(chars[i:i+n]))
                    grams.append(word)
                
                if not words:
                    chars = list(text)
                    for i in range(len(chars) - 1):
                        grams.append(chars[i] + chars[i + 1])
                    for i in range(len(chars) - 2):
                        grams.append(chars[i] + chars[i + 1] + chars[i + 2])
                
                for g in grams:
                    h = int(hashlib.md5(g.encode("utf-8", errors="replace")).hexdigest(), 16)
                    vec[h % self._dim] += 1.0
                
                norm = sum(v * v for v in vec) ** 0.5
                if norm > 0:
                    vec = [v / norm for v in vec]
                return vec
        
        self._embedding_fn = _NgramEmbeddingFunction()
        return self._chromadb_module, self._embedding_fn
    
    def _chroma_dir(self, context: ProjectContext) -> Path:
        return context.data_dir / "chroma"
    
    def _key(self, context: ProjectContext) -> str:
        return str(self._chroma_dir(context).resolve())
    
    def get_client(self, context: ProjectContext) -> Optional[Any]:
        key = self._key(context)
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                if hasattr(client, '_closed') and client._closed:
                    del self._clients[key]
                else:
                    return client
            if self._client_factory is not None:
                client = self._client_factory(context)
            else:
                chromadb_module, embedding_fn = self._ensure_chromadb()
                if chromadb_module is None or embedding_fn is None:
                    return None
                chroma_path = str(self._chroma_dir(context))
                client = chromadb_module.PersistentClient(path=chroma_path)
            self._clients[key] = client
            return client
    
    def get_collection(self, context: ProjectContext) -> Optional[Any]:
        client = self.get_client(context)
        if client is None:
            return None

        _, embedding_fn = self._ensure_chromadb()
        if embedding_fn is None:
            return None

        import warnings
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Could not reconstruct embedding function.*",
                )
                col = client.get_collection(
                    self._collection_name,
                    embedding_function=embedding_fn,
                )
        except Exception as exc:
            if not self._is_collection_missing(exc):
                raise
            client.create_collection(
                name=self._collection_name,
                metadata=dict(NGRAM_COLLECTION_METADATA),
                embedding_function=embedding_fn,
            )
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Could not reconstruct embedding function.*",
                )
                col = client.get_collection(
                    self._collection_name,
                    embedding_function=embedding_fn,
                )
        self._validate_collection_contract(col)
        return col

    def _validate_collection_contract(self, collection: Any) -> None:
        metadata = getattr(collection, "metadata", None)
        if not isinstance(metadata, dict):
            raise VectorEmbeddingContractMissing(
                f"{self._collection_name}: missing embedding contract; "
                f"expected {NGRAM_EMBEDDING_CONTRACT}/"
                f"{NGRAM_EMBEDDING_VERSION}/{NGRAM_EMBEDDING_DIMENSION}"
            )
        contract = metadata.get("embedding_contract")
        version = metadata.get("embedding_version")
        dimension = metadata.get("embedding_dimension")
        if contract is None or version is None or dimension is None:
            raise VectorEmbeddingContractMissing(
                f"{self._collection_name}: incomplete embedding contract; "
                f"expected {NGRAM_EMBEDDING_CONTRACT}/"
                f"{NGRAM_EMBEDDING_VERSION}/{NGRAM_EMBEDDING_DIMENSION}"
            )
        if contract != NGRAM_EMBEDDING_CONTRACT:
            raise VectorEmbeddingContractMismatch(
                f"{self._collection_name}: embedding contract mismatch; "
                f"expected {NGRAM_EMBEDDING_CONTRACT}"
            )
        if version != NGRAM_EMBEDDING_VERSION:
            raise VectorEmbeddingVersionMismatch(
                f"{self._collection_name}: embedding version mismatch; "
                f"expected {NGRAM_EMBEDDING_VERSION}"
            )
        if dimension != NGRAM_EMBEDDING_DIMENSION:
            raise VectorEmbeddingDimensionMismatch(
                f"{self._collection_name}: embedding dimension mismatch; "
                f"expected {NGRAM_EMBEDDING_DIMENSION}"
            )

    @staticmethod
    def _is_collection_missing(exc: Exception) -> bool:
        if isinstance(exc, KeyError):
            return True
        try:
            from chromadb.errors import NotFoundError
        except ImportError:
            return False
        return isinstance(exc, NotFoundError)
    
    def close_client(self, context: ProjectContext) -> None:
        key = self._key(context)
        
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                self._close(client)
                del self._clients[key]
    
    def close_path(self, chroma_dir: Path) -> None:
        key = str(chroma_dir.resolve())
        
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                self._close(client)
                del self._clients[key]
    
    def close_all(self) -> None:
        with self._client_lock:
            for client in self._clients.values():
                self._close(client)
            self._clients.clear()

    @staticmethod
    def _close(client: Any) -> None:
        """Release both the public client and Chroma's Windows file system.

        Chroma 1.x may retain a stopped system in its process cache after
        ``Client.close()``.  Explicitly stopping it prevents a stale SQLite
        handle from keeping a temporary ProjectRoot undeletable on Windows.
        """
        try:
            if hasattr(client, "close"):
                client.close()
        except Exception:
            pass
        try:
            system = getattr(client, "_system", None)
            if system is not None and hasattr(system, "stop"):
                system.stop()
        except Exception:
            pass
        try:
            if hasattr(client, "clear_system_cache"):
                client.clear_system_cache()
        except Exception:
            pass
    
    def has_client(self, context: ProjectContext) -> bool:
        key = self._key(context)
        with self._client_lock:
            return key in self._clients
