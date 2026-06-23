import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from xml.sax.saxutils import escape as xml_escape

from argon.engine.builder import BuilderMixin, _pagerank
from argon.engine.hotspots import GitAnalyzer
from argon.engine.keywords import extract_task_keywords
from argon.engine.scorer import (
    identifier_tokens as _identifier_tokens_fn,
    symbol_tokens as _symbol_tokens_fn,
    symbol_match_profile as _symbol_match_profile_fn,
    score_symbol_for_task as _score_symbol_for_task_fn,
    compute_idf as _compute_idf_fn,
    task_focus_tokens as _task_focus_tokens_fn,
    task_intents as _task_intents_fn,
    is_noise_symbol_for_task as _is_noise_symbol_for_task_fn,
    is_generic_type_symbol as _is_generic_type_symbol_fn,
    is_weak_file_only_match as _is_weak_file_only_match_fn,
    is_unrequested_test_symbol as _is_unrequested_test_symbol_fn,
    is_isolated_focus_match as _is_isolated_focus_match_fn,
    symbol_token_cost as _symbol_token_cost_fn,
)
from argon.engine.snippets import (
    truncate_snippet as _truncate_snippet_fn,
    read_symbol_snippet as _read_symbol_snippet_fn,
    read_contextual_snippet as _read_contextual_snippet_fn,
)
from argon.engine.selector import (
    edge_maps as _edge_maps_fn,
    context_tier as _context_tier_fn,
    support_symbol_factor as _support_symbol_factor_fn,
    neighbor_score as _neighbor_score_fn,
    select_precision_symbols as _select_precision_symbols_fn,
)
from argon.engine.formatter import (
    precision_symbol_block as _precision_symbol_block_fn,
    precision_layers as _precision_layers_fn,
    compact_precision_symbol as _compact_precision_symbol_fn,
    precision_expansion_plan as _precision_expansion_plan_fn,
    fit_expansion_plan as _fit_expansion_plan_fn,
    build_precision_json_payload as _build_precision_json_payload_fn,
    build_precision_compact as _build_precision_compact_fn,
    get_domain_safeguards,
    generate_precision_context as _generate_precision_context_fn,
)
from argon.utils.tokens import TokenCounter, estimate_tokens, resolve_precision_budget


from argon.utils.tokens import PRECISION_BUDGET_PROFILES  # noqa: re-exported for backwards compat

# Backward-compatible re-exports
from argon.engine.builder import _pagerank  # noqa


class ArgonEngine(BuilderMixin):
    # ── Context report ────────────────────────────────────────────────

    def generate_context_report(self, graph: Dict[str, Any], output_path: str, max_tokens: int = 4096):
        header = [
            f"# ARGON PROJECT CONTEXT: {graph['root']}",
            f"Generated: {graph['stats']['timestamp']}",
            f"Files: {graph['stats']['total_files']} | Connections: {graph['stats']['total_connections']}",
            f"Parser: {graph.get('parser_mode', 'regex')}",
            "", "---", "",
        ]
        
        languages = {n.get('type') for n in graph.get('nodes', [])}
        rules = get_domain_safeguards(graph.get('project_domain', 'general'), languages)
        if rules:
            header.append("## AI CODING SAFEGUARDS")
            for r in rules:
                header.append(f"- {r}")
            header.append("")
            header.append("---")
            header.append("")

        header_text = "\n".join(header)
        budget = max_tokens - estimate_tokens(header_text)

        sorted_nodes = sorted(graph['nodes'], key=lambda x: x.get('importance', 0), reverse=True)

        detailed = []
        summary_only = []
        used = 0

        for n in sorted_nodes:
            block_lines = [f"### {n['id']} [{n['type'].upper()} | {n['lines']}L | imp:{n.get('importance', 0):.2f}]"]
            if n.get('summary'):
                block_lines.append(f"> {n['summary']}")
            syms = [f"{s['kind']}:{s['name']}" for s in n.get('symbols', [])]
            if syms:
                block_lines.append(f"- SYMBOLS: {', '.join(syms[:20])}")
            imps = list(dict.fromkeys(n.get('imports', [])))
            if imps:
                block_lines.append(f"- DEPENDS: {', '.join(imps[:10])}")
            block_lines.append("")
            block_text = "\n".join(block_lines)
            cost = estimate_tokens(block_text)

            if used + cost <= budget:
                detailed.append(block_text)
                used += cost
            else:
                summary_only.append(n['id'])

        parts = [header_text] + detailed
        if summary_only:
            remaining = f"\n---\n\n## REMAINING FILES ({len(summary_only)})\n"
            remaining += "\n".join(f"- {p}" for p in summary_only[:200])
            if len(summary_only) > 200:
                remaining += f"\n- ... +{len(summary_only) - 200} more"
            parts.append(remaining)

        output = "\n".join(parts)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)

        total_tokens = estimate_tokens(output)
        detailed_count = len(detailed)
        print(f"[+] ARGON.md: {detailed_count} detailed + {len(summary_only)} listed | ~{total_tokens} tokens")

    # ── Delegation methods (backward-compatible) ──────────────────────

    def _read_symbol_snippet(self, symbol: Dict[str, Any], max_lines: int = 80) -> str:
        return _read_symbol_snippet_fn(self.root, self.parser, symbol, max_lines)

    def _truncate_snippet(self, snippet: str, max_tokens: int) -> str:
        return _truncate_snippet_fn(snippet, max_tokens)

    def _read_contextual_snippet(self, symbol: Dict[str, Any], keywords: List[str], tier: str) -> str:
        return _read_contextual_snippet_fn(self.root, self.parser, symbol, keywords, tier)

    def _task_keywords(self, task: str) -> List[str]:
        return extract_task_keywords(task)

    def _identifier_tokens(self, text: str) -> List[str]:
        return _identifier_tokens_fn(text)

    def _symbol_tokens(self, sym: Dict[str, Any]) -> Set[str]:
        return _symbol_tokens_fn(sym)

    def _symbol_match_profile(self, sym: Dict[str, Any], keywords: List[str]) -> Dict[str, Set[str]]:
        return _symbol_match_profile_fn(sym, keywords)

    def _is_noise_symbol_for_task(self, sym: Dict[str, Any]) -> bool:
        return _is_noise_symbol_for_task_fn(sym)

    def _symbol_token_cost(self, sym: Dict[str, Any], include_code: bool = True) -> int:
        return _symbol_token_cost_fn(sym, self.token_counter, include_code,
                                     read_snippet_fn=lambda s: _read_symbol_snippet_fn(self.root, self.parser, s))

    def _task_intents(self, task: str) -> Set[str]:
        return _task_intents_fn(task)

    def _task_focus_tokens(self, keywords: List[str]) -> Set[str]:
        return _task_focus_tokens_fn(keywords)

    def _is_generic_type_symbol(self, sym: Dict[str, Any]) -> bool:
        return _is_generic_type_symbol_fn(sym)

    def _edge_maps(self, graph: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
        return _edge_maps_fn(graph)

    def _compute_idf(self, symbols: List[Dict[str, Any]]) -> Dict[str, float]:
        return _compute_idf_fn(symbols)

    def _score_symbol_for_task(self, sym: Dict[str, Any], keywords: List[str], idf: Dict[str, float] = None) -> Tuple[float, int]:
        return _score_symbol_for_task_fn(sym, keywords, idf, self.false_positive_blacklist)

    def _is_weak_file_only_match(self, sym: Dict[str, Any], keywords: List[str]) -> bool:
        return _is_weak_file_only_match_fn(sym, keywords)

    def _is_unrequested_test_symbol(self, sym: Dict[str, Any], intents: Set[str]) -> bool:
        return _is_unrequested_test_symbol_fn(sym, intents)

    def _is_isolated_focus_match(self, sym: Dict[str, Any], keywords: List[str]) -> bool:
        return _is_isolated_focus_match_fn(sym, keywords)

    def _support_symbol_factor(self, sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> float:
        return _support_symbol_factor_fn(sym, keywords, intents)

    def _context_tier(self, sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> str:
        return _context_tier_fn(sym, keywords, intents)

    def _neighbor_score(self, sym_id: str, base_score: float, default_factor: float, symbols: Dict[str, Dict[str, Any]], keywords: List[str], idf: Dict[str, float] = None) -> float:
        return _neighbor_score_fn(sym_id, base_score, default_factor, symbols, keywords, idf, self.false_positive_blacklist)

    def _select_precision_symbols(self, graph: Dict[str, Any], task: str, max_tokens: int = 0) -> List[Dict[str, Any]]:
        git = GitAnalyzer(self.root)
        selected, report = _select_precision_symbols_fn(
            graph, task, max_tokens,
            false_positive_blacklist=self.false_positive_blacklist,
            token_counter=self.token_counter,
            read_snippet_fn=(self.root, self.parser),
            semantic_index=self.semantic_index,
            git_analyzer=git,
        )
        self._last_selection_report = report
        return selected

    # ── Precision formatting ──────────────────────────────────────────

    def _precision_symbol_block(self, symbol: Dict[str, Any], output_format: str, keywords: List[str] = None) -> str:
        return _precision_symbol_block_fn(symbol, output_format, self.root, self.parser, keywords)

    def _precision_layers(self, symbols: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        return _precision_layers_fn(symbols)

    def _compact_precision_symbol(self, sym: Dict[str, Any]) -> Dict[str, Any]:
        return _compact_precision_symbol_fn(sym)

    def _precision_expansion_plan(self, selected: List[Dict[str, Any]], full_code_ids: Set[str], included_ids: Set[str], max_items: int = 8) -> List[Dict[str, Any]]:
        return _precision_expansion_plan_fn(selected, full_code_ids, included_ids, max_items)

    def _fit_expansion_plan(self, payload: Dict[str, Any], selected: List[Dict[str, Any]], max_tokens: int, counter: Optional['TokenCounter'] = None, max_items: int = 8) -> None:
        _fit_expansion_plan_fn(payload, selected, max_tokens, counter or self.token_counter, max_items)

    def _build_precision_json_payload(self, graph: Dict[str, Any], task: str, max_tokens: int, budget_profile: str = 'custom') -> str:
        max_tokens_resolved, _ = resolve_precision_budget(max_tokens, budget_profile)
        selected = self._select_precision_symbols(graph, task, max_tokens_resolved)
        return _build_precision_json_payload_fn(
            graph, task, max_tokens, budget_profile,
            selected=selected,
            selection_report=getattr(self, '_last_selection_report', {}),
            keywords=extract_task_keywords(task),
            counter=self.token_counter,
            root=self.root,
            parser=self.parser,
        )

    def _generate_precision_json_output(self, graph: Dict[str, Any], output_path: str, task: str, max_tokens: int, budget_profile: str = 'custom') -> None:
        max_tokens_resolved, _ = resolve_precision_budget(max_tokens, budget_profile)
        selected = self._select_precision_symbols(graph, task, max_tokens_resolved)
        output = _build_precision_json_payload_fn(
            graph, task, max_tokens, budget_profile,
            selected=selected,
            selection_report=getattr(self, '_last_selection_report', {}),
            keywords=extract_task_keywords(task),
            counter=self.token_counter,
            root=self.root,
            parser=self.parser,
        )
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[+] Precision context: {output_path} | {self.token_counter.count(output)} tokens")

    def _generate_precision_compact_output(self, graph: Dict[str, Any], output_path: str, task: str, max_tokens: int, budget_profile: str = 'custom') -> None:
        max_tokens_resolved, _ = resolve_precision_budget(max_tokens, budget_profile)
        selected = self._select_precision_symbols(graph, task, max_tokens_resolved)
        output = _build_precision_compact_fn(
            graph, task, max_tokens_resolved,
            selected=selected,
            selection_report=getattr(self, '_last_selection_report', {}),
            keywords=extract_task_keywords(task),
            root=self.root,
            parser=self.parser,
        )
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[+] Precision compact: {output_path} | {self.token_counter.count(output)} tokens")

    def generate_precision_context(
        self,
        graph: Dict[str, Any],
        output_path: str,
        task: str,
        max_tokens: int = 4096,
        output_format: str = 'xml',
        budget_profile: str = 'custom',
    ) -> None:
        max_tokens_resolved, budget_settings = resolve_precision_budget(max_tokens, budget_profile)
        selected = self._select_precision_symbols(graph, task, max_tokens_resolved)
        selection_report = getattr(self, '_last_selection_report', {})
        
        _generate_precision_context_fn(
            graph=graph,
            output_path=output_path,
            task=task,
            max_tokens=max_tokens_resolved,
            output_format=output_format,
            budget_profile=budget_profile,
            selected=selected,
            selection_report=selection_report,
            keywords=extract_task_keywords(task),
            counter=self.token_counter,
            root=self.root,
            parser=self.parser,
        )
