#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON SEMANTIC v1.0 -- LOCAL EMBEDDING ENGINE
----------------------------------------------
Provides semantic search over symbol graphs using local embeddings.
Supports multiple backends with graceful fallback:
  1. sentence-transformers (best quality, ~100MB model)
  2. Ollama local API (if running)
  3. TF-IDF fallback (zero dependencies, decent quality)
"""

import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# =========================================================================
# BACKEND DETECTION (with JIT auto-install)
# =========================================================================

def _detect_backend() -> str:
    """Detect best available embedding backend. Auto-installs if missing."""
    if hasattr(_detect_backend, '_backend') and _detect_backend._backend is not None:
        return _detect_backend._backend

    # Try sentence-transformers (already installed?)
    try:
        from sentence_transformers import SentenceTransformer
        _detect_backend._model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
        _detect_backend._backend = 'sentence-transformers'
        return _detect_backend._backend
    except ImportError:
        pass

    # Not installed — attempt JIT auto-install
    try:
        from argon_deps import ensure as _ensure_dep
        _st_mod = _ensure_dep(
            "sentence-transformers", "sentence_transformers",
            heavy=True, description="semantic embedding AI model (~2GB with PyTorch)",
        )
        if _st_mod is not None:
            from sentence_transformers import SentenceTransformer
            _detect_backend._model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
            _detect_backend._backend = 'sentence-transformers'
            return _detect_backend._backend
    except Exception:
        pass

    # Fallback: TF-IDF (always available, zero dependencies)
    _detect_backend._backend = 'tfidf'
    return _detect_backend._backend


# =========================================================================
# TOKENIZER (shared)
# =========================================================================

def _tokenize(text: str) -> List[str]:
    """Split text into normalized tokens for TF-IDF or text preparation."""
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[_\-./:\\@]+', ' ', text)
    tokens = re.findall(r'[a-zA-Z0-9]+', text.lower())
    return [t for t in tokens if len(t) > 1]


def _symbol_text(sym: Dict[str, Any]) -> str:
    """Build searchable text from a symbol entry."""
    parts = [
        sym.get('name', ''),
        sym.get('kind', ''),
        sym.get('file', ''),
        sym.get('signature', ''),
    ]
    return ' '.join(p for p in parts if p)


# =========================================================================
# TF-IDF BACKEND (zero dependencies)
# =========================================================================

class TfIdfIndex:
    """Lightweight TF-IDF vector index. No numpy required."""

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.doc_tokens: List[List[str]] = []
        self.idf: Dict[str, float] = {}
        self.doc_vectors: List[Dict[str, float]] = []

    def build(self, symbols: List[Dict[str, Any]]) -> None:
        self.documents = symbols
        self.doc_tokens = [_tokenize(_symbol_text(s)) for s in symbols]

        # Compute IDF
        n = len(self.doc_tokens)
        df: Counter = Counter()
        for tokens in self.doc_tokens:
            for t in set(tokens):
                df[t] += 1
        self.idf = {t: math.log((n + 1) / (count + 1)) + 1 for t, count in df.items()}

        # Compute TF-IDF vectors
        self.doc_vectors = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            total = len(tokens) or 1
            vec = {t: (c / total) * self.idf.get(t, 1.0) for t, c in tf.items()}
            self.doc_vectors.append(vec)

    def query(self, text: str, top_k: int = 20) -> List[Tuple[float, Dict[str, Any]]]:
        query_tokens = _tokenize(text)
        if not query_tokens:
            return []

        qtf = Counter(query_tokens)
        total = len(query_tokens)
        qvec = {t: (c / total) * self.idf.get(t, 1.0) for t, c in qtf.items()}

        results = []
        for i, dvec in enumerate(self.doc_vectors):
            score = _cosine_sparse(qvec, dvec)
            if score > 0.01:
                results.append((score, self.documents[i]))

        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]


def _cosine_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    dot = sum(a[k] * b[k] for k in a if k in b)
    if dot == 0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# =========================================================================
# SENTENCE-TRANSFORMERS BACKEND
# =========================================================================

class SentenceTransformerIndex:
    """Embedding index using sentence-transformers."""

    def __init__(self, model):
        self.documents: List[Dict[str, Any]] = []
        self.embeddings = None  # numpy array
        self._model = model

    def build(self, symbols: List[Dict[str, Any]]) -> None:
        import numpy as np
        self.documents = symbols
        texts = [_symbol_text(s) for s in symbols]
        self.embeddings = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        # Normalize
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.embeddings = self.embeddings / norms

    def query(self, text: str, top_k: int = 20) -> List[Tuple[float, Dict[str, Any]]]:
        import numpy as np
        q = self._model.encode([text], convert_to_numpy=True)
        q = q / (np.linalg.norm(q) or 1)
        scores = (self.embeddings @ q.T).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(float(scores[i]), self.documents[i]) for i in top_indices if scores[i] > 0.01]


# =========================================================================
# OLLAMA BACKEND
# =========================================================================

class OllamaIndex:
    """Embedding index using Ollama local API."""

    EMBED_MODEL = 'nomic-embed-text'

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.embeddings: List[List[float]] = []

    def _embed(self, texts: List[str]) -> List[List[float]]:
        import urllib.request
        results = []
        # Batch in chunks of 32
        for i in range(0, len(texts), 32):
            batch = texts[i:i + 32]
            payload = json.dumps({'model': self.EMBED_MODEL, 'input': batch}).encode()
            req = urllib.request.Request(
                'http://localhost:11434/api/embed',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                results.extend(data.get('embeddings', []))
        return results

    def build(self, symbols: List[Dict[str, Any]]) -> None:
        self.documents = symbols
        texts = [_symbol_text(s) for s in symbols]
        self.embeddings = self._embed(texts)

    def query(self, text: str, top_k: int = 20) -> List[Tuple[float, Dict[str, Any]]]:
        q_emb = self._embed([text])[0]
        results = []
        for i, emb in enumerate(self.embeddings):
            score = _cosine_dense(q_emb, emb)
            if score > 0.01:
                results.append((score, self.documents[i]))
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]


def _cosine_dense(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two dense vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# =========================================================================
# PUBLIC API
# =========================================================================

class SemanticIndex:
    """
    Unified semantic search index for ARGON symbol graphs.
    Auto-selects the best available backend.
    """

    def __init__(self):
        self.backend_name = _detect_backend()
        if self.backend_name == 'sentence-transformers':
            self._index = SentenceTransformerIndex(_detect_backend._model)
        elif self.backend_name == 'ollama':
            self._index = OllamaIndex()
        else:
            self._index = TfIdfIndex()
        self._built = False

    def build_from_graph(self, graph: Dict[str, Any]) -> int:
        """Build the index from an ARGON graph dict. Returns symbol count."""
        symbols = graph.get('symbols', [])
        if not symbols:
            return 0
        self._index.build(symbols)
        self._built = True
        return len(symbols)

    def query(self, text: str, top_k: int = 20) -> List[Tuple[float, Dict[str, Any]]]:
        """Query the index. Returns list of (score, symbol_dict)."""
        if not self._built:
            return []
        return self._index.query(text, top_k)

    def save(self, path: str) -> None:
        """Save index metadata (for TF-IDF: IDF + doc data). Not needed for model-based backends."""
        if self.backend_name == 'tfidf' and isinstance(self._index, TfIdfIndex):
            data = {
                'backend': 'tfidf',
                'idf': self._index.idf,
                'documents': [
                    {'id': d.get('id', ''), 'name': d.get('name', ''), 'file': d.get('file', '')}
                    for d in self._index.documents
                ],
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)

    @property
    def is_built(self) -> bool:
        return self._built
