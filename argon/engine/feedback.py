"""Feedback loop for learning from user interactions."""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


class FeedbackStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.feedback_path = os.path.join(self.root, '.argon_feedback.jsonl')
        self.weights_path = os.path.join(self.root, '.argon_learned_weights.json')
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.feedback_path):
            return
        try:
            with open(self.feedback_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._entries.append(json.loads(line))
        except Exception:
            pass

    def record(self, task: str, accepted: List[str], rejected: List[str], context: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            'task': task,
            'accepted': accepted,
            'rejected': rejected,
            'timestamp': datetime.now().isoformat(),
            'context': context or {},
        }
        self._entries.append(entry)
        try:
            with open(self.feedback_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def get_training_data(self) -> List[Dict[str, Any]]:
        return self._entries

    def get_accepted_symbols(self) -> set:
        accepted = set()
        for entry in self._entries:
            accepted.update(entry.get('accepted', []))
        return accepted

    def get_rejected_symbols(self) -> set:
        rejected = set()
        for entry in self._entries:
            rejected.update(entry.get('rejected', []))
        return rejected

    def save_weights(self, weights: Dict[str, Any]) -> None:
        try:
            with open(self.weights_path, 'w', encoding='utf-8') as f:
                json.dump(weights, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def load_weights(self) -> Dict[str, Any]:
        if not os.path.exists(self.weights_path):
            return {}
        try:
            with open(self.weights_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def has_feedback(self) -> bool:
        return len(self._entries) > 0
