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
from typing import Any, Dict, Optional

from core.project_context import ProjectContext


class VectorClientManager:
    _instance: Optional[VectorClientManager] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> VectorClientManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._clients: Dict[str, Any] = {}
                cls._instance._client_lock = threading.RLock()
                cls._instance._chromadb_module = None
                cls._instance._embedding_fn = None
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
                self._dim = 512
            
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
        chromadb_module, embedding_fn = self._ensure_chromadb()
        if chromadb_module is None or embedding_fn is None:
            return None
        
        key = self._key(context)
        
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                if hasattr(client, '_closed') and client._closed:
                    del self._clients[key]
                else:
                    return client
            
            chroma_path = str(self._chroma_dir(context))
            client = chromadb_module.PersistentClient(path=chroma_path)
            self._clients[key] = client
            return client
    
    def get_collection(self, context: ProjectContext) -> Optional[Any]:
        client = self.get_client(context)
        if client is None:
            return None
        
        chromadb_module, embedding_fn = self._ensure_chromadb()
        if chromadb_module is None or embedding_fn is None:
            return None
        
        collection_name = "storyos_memory"
        
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Could not reconstruct embedding function.*",
                )
                col = client.get_collection(collection_name)
                col._embedding_function = embedding_fn
                return col
        except Exception:
            return client.create_collection(name=collection_name, embedding_function=embedding_fn)
    
    def close_client(self, context: ProjectContext) -> None:
        key = self._key(context)
        
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass
                del self._clients[key]
    
    def close_path(self, chroma_dir: Path) -> None:
        key = str(chroma_dir.resolve())
        
        with self._client_lock:
            if key in self._clients:
                client = self._clients[key]
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass
                del self._clients[key]
    
    def close_all(self) -> None:
        with self._client_lock:
            for client in self._clients.values():
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass
            self._clients.clear()
    
    def has_client(self, context: ProjectContext) -> bool:
        key = self._key(context)
        with self._client_lock:
            return key in self._clients