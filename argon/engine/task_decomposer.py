"""Task decomposition for complex multi-domain requests."""

import re
from typing import Any, Dict, List, Optional, Set, Tuple


CONJUNCTIONS = {'and', 'y', 'e', '&', 'plus', 'also', 'with', 'con', 'und', 'et'}
ACTION_VERBS = {
    'add', 'create', 'implement', 'fix', 'update', 'modify', 'refactor', 'optimize',
    'remove', 'delete', 'improve', 'enhance', 'extend', 'support', 'handle',
    'agregar', 'crear', 'implementar', 'arreglar', 'actualizar', 'modificar',
}


class TaskDecomposer:
    def __init__(self):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    def decompose(self, task: str) -> List[Dict[str, Any]]:
        task_lower = task.lower().strip()
        if task_lower in self._cache:
            return self._cache[task_lower]

        parts = self._split_conjunctions(task_lower)
        if len(parts) <= 1:
            result = [{'text': task_lower, 'action': self._detect_action(task_lower), 'keywords': self._extract_keywords(task_lower)}]
            self._cache[task_lower] = result
            return result

        subtasks = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            action = self._detect_action(part)
            keywords = self._extract_keywords(part)
            if keywords:
                subtasks.append({
                    'text': part,
                    'action': action,
                    'keywords': keywords,
                })

        if not subtasks:
            subtasks = [{'text': task_lower, 'action': self._detect_action(task_lower), 'keywords': self._extract_keywords(task_lower)}]

        self._cache[task_lower] = subtasks
        return subtasks

    def _split_conjunctions(self, task: str) -> List[str]:
        tokens = re.findall(r'[\w]+', task)
        parts = []
        current = []
        for token in tokens:
            if token in CONJUNCTIONS and current:
                parts.append(' '.join(current))
                current = []
            else:
                current.append(token)
        if current:
            parts.append(' '.join(current))
        return parts

    def _detect_action(self, text: str) -> str:
        tokens = set(text.split())
        for verb in ACTION_VERBS:
            if verb in tokens:
                return verb
        return 'modify'

    def _extract_keywords(self, text: str) -> List[str]:
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'and', 'or', 'not', 'this', 'that', 'it', 'i', 'we', 'you', 'need', 'want', 'make', 'add',
            'when', 'while', 'during', 'after', 'before', 'el', 'la', 'los', 'las', 'un', 'una', 'de',
            'del', 'en', 'con', 'por', 'para', 'que', 'como', 'es', 'son', 'hay', 'quiero', 'necesito',
        }
        tokens = re.findall(r'[\w@./-]+', text)
        return [t for t in tokens if len(t) > 2 and t not in stop_words]

    def merge_results(self, subtask_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        seen_ids = set()
        merged = []
        for results in subtask_results:
            for sym in results:
                sym_id = sym.get('id', '')
                if sym_id and sym_id not in seen_ids:
                    seen_ids.add(sym_id)
                    merged.append(sym)
                elif not sym_id:
                    merged.append(sym)
        return merged

    def merge_with_priority(self, subtask_results: List[Tuple[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
        symbol_appearances: Dict[str, int] = {}
        symbol_data: Dict[str, Dict[str, Any]] = {}
        for subtask_text, results in subtask_results:
            for sym in results:
                sym_id = sym.get('id', '')
                if sym_id:
                    symbol_appearances[sym_id] = symbol_appearances.get(sym_id, 0) + 1
                    if sym_id not in symbol_data:
                        symbol_data[sym_id] = sym

        scored = []
        for sym_id, count in symbol_appearances.items():
            sym = symbol_data[sym_id]
            priority_score = count * 10 + float(sym.get('selection_score', 0))
            scored.append((priority_score, sym))

        scored.sort(key=lambda x: -x[0])
        return [sym for _, sym in scored]
