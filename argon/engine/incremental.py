"""Incremental context generation with progressive disclosure (3-wave selection)."""

from typing import Any, Dict, List, Optional, Set, Tuple

from argon.engine.scorer import (
    symbol_match_profile, task_focus_tokens,
    is_noise_symbol_for_task, is_weak_file_only_match,
)
from argon.engine.selector import context_tier


class WaveConfig:
    def __init__(self, name: str, max_tokens_ratio: float, include_code: bool, max_snippet_tokens: int):
        self.name = name
        self.max_tokens_ratio = max_tokens_ratio
        self.include_code = include_code
        self.max_snippet_tokens = max_snippet_tokens


WAVE_1 = WaveConfig('minimal', 0.30, False, 0)
WAVE_2 = WaveConfig('expand', 0.70, True, 40)
WAVE_3 = WaveConfig('deep', 1.00, True, 120)

WAVES = [WAVE_1, WAVE_2, WAVE_3]


class IncrementalSelector:
    def __init__(self, all_symbols: List[Dict[str, Any]], keywords: List[str], intents: Set[str], total_budget: int):
        self.all_symbols = all_symbols
        self.keywords = keywords
        self.intents = intents
        self.total_budget = total_budget
        self._selected_by_id: Dict[str, Dict[str, Any]] = {}
        self._current_wave = 0
        self._expanded_ids: Set[str] = set()

    def get_wave_symbols(self, wave_index: int, read_snippet_fn=None) -> List[Dict[str, Any]]:
        if wave_index >= len(WAVES):
            wave_index = len(WAVES) - 1
        self._current_wave = wave_index
        wave = WAVES[wave_index]
        budget = int(self.total_budget * wave.max_tokens_ratio)

        candidates = []
        for sym in self.all_symbols:
            if is_noise_symbol_for_task(sym):
                continue
            if not wave.include_code:
                tier = context_tier(sym, self.keywords, self.intents)
                if tier == 'support':
                    compact = self._compact_symbol(sym)
                    compact['context_tier'] = tier
                    compact['_wave'] = wave_index
                    candidates.append(compact)
                elif tier in ('critical', 'workflow'):
                    compact = self._compact_symbol(sym)
                    compact['context_tier'] = tier
                    compact['_wave'] = wave_index
                    candidates.append(compact)
            else:
                tier = context_tier(sym, self.keywords, self.intents)
                compact = self._compact_symbol(sym)
                compact['context_tier'] = tier
                compact['_wave'] = wave_index
                if read_snippet_fn:
                    compact['_snippet'] = read_snippet_fn(sym)
                candidates.append(compact)

        selected = []
        used_tokens = 0
        for sym in candidates:
            est_tokens = len(sym.get('signature', '').split()) + 10
            if sym.get('_snippet'):
                est_tokens += len(sym['_snippet'].split())
            if used_tokens + est_tokens <= budget:
                selected.append(sym)
                used_tokens += est_tokens
                self._selected_by_id[sym.get('id', '')] = sym

        return selected

    def expand_symbol(self, sym_id: str, read_snippet_fn=None) -> Optional[Dict[str, Any]]:
        if sym_id in self._expanded_ids:
            return None
        self._expanded_ids.add(sym_id)

        for sym in self.all_symbols:
            if sym.get('id') == sym_id:
                compact = self._compact_symbol(sym)
                compact['context_tier'] = context_tier(sym, self.keywords, self.intents)
                compact['_wave'] = 2
                if read_snippet_fn:
                    compact['_snippet'] = read_snippet_fn(sym)
                self._selected_by_id[sym_id] = compact
                return compact
        return None

    def _compact_symbol(self, sym: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': sym.get('id', ''),
            'name': sym.get('name', ''),
            'kind': sym.get('kind', ''),
            'file': sym.get('file', ''),
            'start_line': sym.get('start_line', 0),
            'end_line': sym.get('end_line', 0),
            'signature': sym.get('signature', ''),
            'exported': sym.get('exported', False),
            'selection_score': sym.get('selection_score', 0),
            'inbound_calls': sym.get('inbound_calls', 0),
            'outbound_calls': sym.get('outbound_calls', 0),
        }

    def get_expansion_plan(self, max_items: int = 8) -> List[Dict[str, Any]]:
        plan = []
        for sym in self.all_symbols:
            if sym.get('id') not in self._selected_by_id:
                compact = self._compact_symbol(sym)
                compact['context_tier'] = context_tier(sym, self.keywords, self.intents)
                plan.append(compact)
                if len(plan) >= max_items:
                    break
        return plan

    @property
    def selected_count(self) -> int:
        return len(self._selected_by_id)

    @property
    def current_wave(self) -> int:
        return self._current_wave
