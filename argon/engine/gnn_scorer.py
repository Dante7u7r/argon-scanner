"""Graph Neural Network scorer for structural importance prediction (exploratory)."""

import math
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class SimpleGNN:
    def __init__(self, input_dim: int = 16, hidden_dim: int = 64, output_dim: int = 1):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.W1 = None
        self.b1 = None
        self.W2 = None
        self.b2 = None
        self._initialized = False

    def _init_weights(self) -> None:
        if not HAS_NUMPY:
            return
        scale1 = math.sqrt(2.0 / self.input_dim)
        scale2 = math.sqrt(2.0 / self.hidden_dim)
        self.W1 = np.random.randn(self.input_dim, self.hidden_dim).astype(np.float32) * scale1
        self.b1 = np.zeros(self.hidden_dim, dtype=np.float32)
        self.W2 = np.random.randn(self.hidden_dim, self.output_dim).astype(np.float32) * scale2
        self.b2 = np.zeros(self.output_dim, dtype=np.float32)
        self._initialized = True

    def forward(self, X: 'np.ndarray') -> 'np.ndarray':
        if not self._initialized:
            self._init_weights()
        if not self._initialized:
            return np.zeros(len(X), dtype=np.float32)

        h = X @ self.W1 + self.b1
        h = np.maximum(h, 0)
        h = h @ self.W2 + self.b2
        return h.flatten()

    def aggregate_neighbors(self, node_features: 'np.ndarray', adj_list: List[List[int]]) -> 'np.ndarray':
        n = len(node_features)
        aggregated = np.zeros_like(node_features)
        for i in range(n):
            neighbors = adj_list[i] if i < len(adj_list) else []
            if neighbors:
                neighbor_features = node_features[neighbors]
                aggregated[i] = np.mean(neighbor_features, axis=0)
            else:
                aggregated[i] = node_features[i]
        return aggregated

    def predict_importance(self, node_features: 'np.ndarray', adj_list: List[List[int]]) -> 'np.ndarray':
        if not HAS_NUMPY or not self._initialized:
            return np.ones(len(node_features), dtype=np.float32) * 0.5

        aggregated = self.aggregate_neighbors(node_features, adj_list)
        combined = np.concatenate([node_features, aggregated], axis=1)
        if combined.shape[1] != self.input_dim:
            if combined.shape[1] > self.input_dim:
                combined = combined[:, :self.input_dim]
            else:
                pad = np.zeros((combined.shape[0], self.input_dim - combined.shape[1]), dtype=np.float32)
                combined = np.concatenate([combined, pad], axis=1)
        return self.forward(combined)


def extract_node_features(sym: Dict[str, Any], keywords: List[str]) -> List[float]:
    kind = str(sym.get('kind', '')).lower()
    name_len = len(sym.get('name', ''))
    sig_len = len(sym.get('signature', ''))
    line_count = int(sym.get('end_line', 0)) - int(sym.get('start_line', 0)) + 1

    return [
        1.0 if kind == 'func' else 0.0,
        1.0 if kind in ('class', 'struct') else 0.0,
        1.0 if kind == 'interface' else 0.0,
        1.0 if kind == 'enum' else 0.0,
        1.0 if sym.get('exported') else 0.0,
        min(name_len / 30.0, 1.0),
        min(sig_len / 100.0, 1.0),
        min(line_count / 200.0, 1.0),
        min(int(sym.get('inbound_calls') or 0) / 10.0, 1.0),
        min(int(sym.get('outbound_calls') or 0) / 10.0, 1.0),
        min(int(sym.get('named_imports') or 0) / 5.0, 1.0),
        min(int(sym.get('resolved_imports') or 0) / 5.0, 1.0),
        float(sym.get('rank', 0)),
        float(sym.get('pagerank', 0)),
        1.0 if 'test' in str(sym.get('file', '')).lower() else 0.0,
        0.0,
    ]


def build_adjacency_list(symbols: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[List[int]]:
    id_to_idx = {s.get('id', ''): i for i, s in enumerate(symbols)}
    adj = [[] for _ in range(len(symbols))]
    for edge in edges:
        src_idx = id_to_idx.get(edge.get('source', ''))
        dst_idx = id_to_idx.get(edge.get('target', ''))
        if src_idx is not None and dst_idx is not None:
            if dst_idx not in adj[src_idx]:
                adj[src_idx].append(dst_idx)
            if src_idx not in adj[dst_idx]:
                adj[dst_idx].append(src_idx)
    return adj
