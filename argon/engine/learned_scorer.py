"""Learned scoring model using gradient boosting for symbol relevance prediction."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

from argon.engine.scorer import identifier_tokens, symbol_tokens, task_focus_tokens


FEATURE_NAMES = [
    'task_score_norm', 'call_score', 'graph_score', 'keyword_overlap_count',
    'file_keyword_overlap', 'sig_keyword_overlap', 'is_func', 'is_class',
    'is_interface', 'is_exported', 'is_test', 'line_count_norm',
    'inbound_calls_norm', 'outbound_calls_norm', 'named_imports_norm',
]


def extract_features(sym: Dict[str, Any], keywords: List[str], idf: Optional[Dict[str, float]] = None, max_task_score: float = 1.0) -> List[float]:
    name_tokens = set(identifier_tokens(sym.get('name', '')))
    file_tokens = set(identifier_tokens(sym.get('file', '')))
    sig_tokens = set(identifier_tokens(sym.get('signature', '')))
    kw_set = set(keywords)

    overlap = kw_set & name_tokens
    file_overlap = kw_set & file_tokens
    sig_overlap = kw_set & sig_tokens

    task_score = 0.0
    if idf:
        for kw in overlap:
            task_score += idf.get(kw, 1.0) * 1.5
        for kw in file_overlap:
            task_score += idf.get(kw, 1.0) * 0.45
    else:
        task_score = len(overlap) * 1.5 + len(file_overlap) * 0.45

    task_score_norm = min(task_score / (max_task_score or 1.0), 1.0)
    call_score = min(int(sym.get('inbound_calls') or 0), 8) / 8
    graph_score = float(sym.get('rank', 0))

    kind = str(sym.get('kind', '')).lower()
    line_count = int(sym.get('end_line', 0)) - int(sym.get('start_line', 0)) + 1

    return [
        task_score_norm,
        call_score,
        graph_score,
        len(overlap) / max(len(keywords), 1),
        len(file_overlap) / max(len(keywords), 1),
        len(sig_overlap) / max(len(keywords), 1),
        1.0 if kind == 'func' else 0.0,
        1.0 if kind in ('class', 'struct') else 0.0,
        1.0 if kind == 'interface' else 0.0,
        1.0 if sym.get('exported') else 0.0,
        1.0 if 'test' in str(sym.get('file', '')).lower() else 0.0,
        min(line_count / 200.0, 1.0),
        min(int(sym.get('inbound_calls') or 0) / 20.0, 1.0),
        min(int(sym.get('outbound_calls') or 0) / 20.0, 1.0),
        min(int(sym.get('named_imports') or 0) / 10.0, 1.0),
    ]


class LearnedScorer:
    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.model_path = model_path
        if HAS_LGBM and model_path and os.path.exists(model_path):
            self._load_model(model_path)

    def _load_model(self, path: str) -> None:
        try:
            self.model = lgb.Booster(model_file=path)
        except Exception:
            self.model = None

    def save_model(self, path: str) -> None:
        if self.model:
            self.model.save_model(path)

    def predict(self, features: List[float]) -> float:
        if not self.model or not HAS_LGBM:
            return 0.0
        try:
            import numpy as np
            X = np.array([features], dtype=np.float32)
            pred = self.model.predict(X)
            return float(pred[0])
        except Exception:
            return 0.0

    def train(self, X: List[List[float]], y: List[float], num_boost_round: int = 100) -> None:
        if not HAS_LGBM:
            return
        import numpy as np
        X_arr = np.array(X, dtype=np.float32)
        y_arr = np.array(y, dtype=np.float32)
        train_data = lgb.Dataset(X_arr, label=y_arr)
        params = {
            'objective': 'regression',
            'metric': 'mse',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.9,
            'verbose': -1,
        }
        self.model = lgb.train(params, train_data, num_boost_round=num_boost_round)


def score_with_learned(sym: Dict[str, Any], keywords: List[str], idf: Optional[Dict[str, float]] = None, max_task_score: float = 1.0, learned_scorer: Optional[LearnedScorer] = None, lexical_score: float = 0.0) -> float:
    if not learned_scorer or not learned_scorer.model:
        return lexical_score
    features = extract_features(sym, keywords, idf, max_task_score)
    learned_score = learned_scorer.predict(features)
    return 0.6 * lexical_score + 0.4 * learned_score
