"""Budget-aware symbol selection with MMR diversity and greedy allocation."""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from argon.engine.keywords import extract_task_keywords
from argon.engine.roles import role_score_boost
from argon.engine.testmap import find_test_counterparts as _find_test_counterparts
from argon.engine.scorer import (
    clear_score_cache,
    compute_idf,
    identifier_tokens,
    is_generic_type_symbol,
    is_isolated_focus_match,
    is_noise_symbol_for_task,
    is_unrequested_test_symbol,
    is_weak_file_only_match,
    score_symbol_for_task,
    symbol_match_profile,
    symbol_tokens,
    symbol_token_cost,
    task_focus_tokens,
    task_intents,
)
from argon.engine.snippets import read_symbol_snippet


def _personalized_pagerank(
    node_ids: List[str],
    edges: List[Dict[str, Any]],
    seed_weights: Dict[str, float],
    iterations: int = 40,
    damping: float = 0.85,
    convergence_threshold: float = 1e-6,
) -> Dict[str, float]:
    """PageRank with task-biased teleport vector.

    Instead of uniform teleport (1-d)/N, teleports proportionally to seed_weights,
    concentrating rank on the task-relevant subgraph.
    """
    if not node_ids:
        return {}
    ids = list(dict.fromkeys(node_ids))
    n = len(ids)
    if n == 0:
        return {}
    id_to_idx = {sid: i for i, sid in enumerate(ids)}

    incoming: Dict[str, List[str]] = {i: [] for i in ids}
    outgoing_count: Dict[str, int] = {i: 0 for i in ids}
    valid = set(ids)
    for edge in edges:
        src = edge.get('source', '')
        dst = edge.get('target', '')
        if src in valid and dst in valid and src != dst:
            incoming[dst].append(src)
            outgoing_count[src] += 1

    total_weight = sum(seed_weights.values()) or 1.0
    seed = {}
    for sid in ids:
        w = seed_weights.get(sid, 0.0)
        seed[sid] = w / total_weight if total_weight > 0 else 1.0 / n

    rank = {i: 1.0 / n for i in ids}
    for _ in range(iterations):
        sink = sum(rank[i] for i in ids if outgoing_count[i] == 0)
        new_rank: Dict[str, float] = {}
        delta = 0.0
        for i in ids:
            value = (1 - damping) * seed.get(i, 1.0 / n)
            value += damping * sink / n
            value += damping * sum(
                rank[src] / outgoing_count[src]
                for src in incoming[i]
                if outgoing_count[src]
            )
            new_rank[i] = value
            delta += abs(value - rank[i])
        rank = new_rank
        if delta < convergence_threshold:
            break
    max_rank = max(rank.values()) or 1.0
    return {k: v / max_rank for k, v in rank.items()}


def edge_maps(graph: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    incoming: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    outgoing: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for edge in graph.get('symbol_edges', []):
        source = edge.get('source')
        target = edge.get('target')
        if source and target:
            outgoing[source].append(edge)
            incoming[target].append(edge)
    return incoming, outgoing


def _is_non_core_dir(file_path: str) -> bool:
    """Files in examples, benchmarks, demos, docs, tests are not core implementation."""
    fp = f'/{file_path}'
    for seg in ('/examples/', '/example/', '/benchmarks/', '/benchmark/',
                '/demo/', '/demos/', '/docs/', '/doc/', '/samples/',
                '/sample/', '/scripts/', '/tools/'):
        if seg in fp:
            return True
    return False


def context_tier(sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> str:
    profile = symbol_match_profile(sym, keywords)
    focus = task_focus_tokens(keywords)
    focus_name_or_signature = focus & (profile['name'] | profile['signature'])
    file_path = str(sym.get('file', '')).lower()
    kind = str(sym.get('kind', '')).lower()
    is_test = 'test' in file_path or 'spec' in file_path
    is_model = '/models/' in file_path or '\\models\\' in file_path or kind in {'class', 'interface', 'type', 'enum', 'struct'}
    is_func = kind == 'func'
    structural_signal = int(sym.get('inbound_calls') or 0) + int(sym.get('outbound_calls') or 0)

    if is_test:
        return 'workflow' if 'tests' in intents else 'support'
    if is_func and focus_name_or_signature:
        return 'critical'
    if is_func and not is_model and (focus & profile['file'] and sym.get('exported')):
        return 'critical'
    if is_model and profile['name'] and sym.get('exported'):
        return 'critical'
    if is_model and focus_name_or_signature:
        return 'critical'
    if is_func and not is_model and profile['all'] and structural_signal > 0:
        return 'workflow'
    if is_model and profile['all']:
        return 'workflow'
    return 'support'


def support_symbol_factor(sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> float:
    focus = task_focus_tokens(keywords)
    file_path = str(sym.get('file', '')).lower()
    if 'tests' not in intents and ('test' in file_path or 'spec' in file_path):
        return 0.55
    if not focus:
        return 1.0
    profile = symbol_match_profile(sym, keywords)
    focus_overlap = focus & profile['all']
    if focus_overlap:
        return 1.0

    kind = str(sym.get('kind', '')).lower()
    name = str(sym.get('name', ''))
    is_model = '/models/' in file_path or '\\models\\' in file_path or kind in {'class', 'interface', 'type', 'enum', 'struct'}
    if is_model:
        return 0.25
    if profile['all'] and not focus_overlap:
        return 0.58
    if name and name[:1].isupper() and not profile['name']:
        return 0.70
    return 1.0


def neighbor_score(sym_id: str, base_score: float, default_factor: float, symbols: Dict[str, Dict[str, Any]], keywords: List[str], idf: Optional[Dict[str, float]] = None, false_positive_blacklist: Optional[set] = None) -> float:
    sym = symbols.get(sym_id)
    if not sym:
        return 0.0
    task_score, overlap_count = score_symbol_for_task(sym, keywords, idf, false_positive_blacklist)
    if overlap_count:
        factor = default_factor
    elif task_score > 0:
        factor = default_factor * 0.75
    else:
        factor = min(default_factor, 0.035)
    return max(base_score * factor, task_score * 0.35)


def select_precision_symbols(graph: Dict[str, Any], task: str, max_tokens: int = 0, false_positive_blacklist: Optional[set] = None, token_counter=None, read_snippet_fn=None, semantic_index=None, git_analyzer=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    clear_score_cache()
    keywords = extract_task_keywords(task)
    intents = task_intents(task)
    all_symbols = graph.get('symbols', [])
    symbols = {s['id']: s for s in all_symbols}
    idf = compute_idf(all_symbols)
    incoming, outgoing = edge_maps(graph)
    candidates: Dict[str, Dict[str, Any]] = {}
    report: Dict[str, Any] = {
        'keywords': keywords,
        'intents': sorted(intents),
        'direct_matches': 0,
        'callers': 0,
        'callees': 0,
        'import_neighbors': 0,
        'tests': 0,
        'global_fallback': 0,
        'generic_types_penalized': 0,
    }

    def add(sym_id: str, score: float, reason: str) -> None:
        sym = symbols.get(sym_id)
        if not sym:
            return
        if is_noise_symbol_for_task(sym):
            report['noise_symbols_filtered'] = report.get('noise_symbols_filtered', 0) + 1
            return
        if is_unrequested_test_symbol(sym, intents):
            report['unrequested_tests_filtered'] = report.get('unrequested_tests_filtered', 0) + 1
            return
        if 'bugfix' not in intents and is_weak_file_only_match(sym, keywords):
            report['weak_file_matches_filtered'] = report.get('weak_file_matches_filtered', 0) + 1
            return
        if reason in {'callers', 'callees', 'import_neighbors'}:
            profile = symbol_match_profile(sym, keywords)
            tier = context_tier(sym, keywords, intents)
            kind = str(sym.get('kind', '')).lower()
            structural_model = kind in {'class', 'interface', 'type', 'enum', 'struct'}
            if tier == 'support' and not profile['all'] and not structural_model:
                report['non_task_neighbors_filtered'] = report.get('non_task_neighbors_filtered', 0) + 1
                return
        current = candidates.get(sym_id)
        if current is None:
            item = dict(sym)
            item['selection_score'] = round(score, 6)
            item['selection_reasons'] = [reason]
            item['task_token_overlap'] = sorted(set(keywords) & symbol_tokens(sym))
            item['context_tier'] = context_tier(sym, keywords, intents)
            candidates[sym_id] = item
            if reason in report:
                report[reason] += 1
            return
        if score > current.get('selection_score', 0):
            current['selection_score'] = round(score, 6)
        if reason not in current['selection_reasons']:
            current['selection_reasons'].append(reason)
            if reason in report:
                report[reason] += 1

    seed_scores = []
    # Single scoring pass: compute task score for every symbol ONCE and reuse.
    # Previously this was computed three separate times (max_task_score,
    # seed_weights, and the main loop). The scorer has an internal cache, but
    # consolidating here removes the repeated key-construction and dict lookups
    # and makes the control flow explicit.
    task_scores: Dict[str, Tuple[float, int]] = {}
    all_task_scores: List[float] = []
    for sym in graph.get('symbols', []):
        ts, oc = score_symbol_for_task(sym, keywords, idf, false_positive_blacklist, semantic_index, task)
        task_scores[sym['id']] = (ts, oc)
        all_task_scores.append(ts)
    max_task_score = max(all_task_scores) if all_task_scores else 1.0
    if max_task_score == 0:
        max_task_score = 1.0

    # Personalized PageRank — teleport biased toward task-matched symbols
    seed_weights: Dict[str, float] = {sid: ts for sid, (ts, _oc) in task_scores.items() if ts > 0}
    personalized_rank = _personalized_pagerank(
        [s['id'] for s in graph.get('symbols', [])],
        graph.get('symbol_edges', []),
        seed_weights,
    ) if seed_weights else {}

    for sym in graph.get('symbols', []):
        task_score, overlap_count = task_scores[sym['id']]
        generic = is_generic_type_symbol(sym)
        generic_penalty = 0.45 if generic and overlap_count == 0 and 'types' not in intents else 1.0
        if generic_penalty < 1:
            report['generic_types_penalized'] = report.get('generic_types_penalized', 0) + 1
        static_rank = float(sym.get('rank', 0))
        pers_rank = personalized_rank.get(sym['id'], 0.0)
        graph_score = 0.4 * static_rank + 0.6 * pers_rank if personalized_rank else static_rank
        call_score = min(int(sym.get('inbound_calls') or 0), 8) / 8
        sf = support_symbol_factor(sym, keywords, intents)
        if sf < 1:
            report['support_symbols_demoted'] = report.get('support_symbols_demoted', 0) + 1
        line_count = int(sym.get('end_line', 0)) - int(sym.get('start_line', 0)) + 1
        if line_count > 100:
            size_penalty = 0.7
        elif line_count > 50:
            size_penalty = 0.85
        else:
            size_penalty = 1.0
        task_norm = task_score / max_task_score
        role_boost = role_score_boost(sym.get('role', ''))
        file_path = sym.get('file', '').lower()
        non_core_penalty = 0.6 if _is_non_core_dir(file_path) else 1.0
        final = ((task_norm * 0.55) + (call_score * 0.25) + (graph_score * 0.20)) * generic_penalty * sf * size_penalty * role_boost * non_core_penalty
        if git_analyzer and git_analyzer.has_git:
            hotspot = git_analyzer.get_hotspots().get(sym.get('file', ''), 0.0)
            final *= 1.0 + (hotspot * 0.40)
        if task_score > 0:
            if is_noise_symbol_for_task(sym):
                report['noise_symbols_filtered'] = report.get('noise_symbols_filtered', 0) + 1
                continue
            if is_unrequested_test_symbol(sym, intents):
                report['unrequested_tests_filtered'] = report.get('unrequested_tests_filtered', 0) + 1
                continue
            if 'bugfix' not in intents and is_weak_file_only_match(sym, keywords):
                report['weak_file_matches_filtered'] = report.get('weak_file_matches_filtered', 0) + 1
                continue
            if is_isolated_focus_match(sym, keywords):
                report['isolated_focus_matches_filtered'] = report.get('isolated_focus_matches_filtered', 0) + 1
                continue
            seed_scores.append((final, task_score, sym['id']))
            add(sym['id'], final, 'direct_matches')

    seed_scores.sort(reverse=True)
    min_relevance = 0.15
    seed_scores = [(f, t, sid) for f, t, sid in seed_scores if t >= min_relevance or f >= 0.3]
    mmr_scores = []
    file_counts = {}
    diversity_penalty = 0.7
    for final, task_score, sym_id in seed_scores:
        file_path = symbols.get(sym_id, {}).get('file', '')
        count = file_counts.get(file_path, 0)
        mmr_score = final * (diversity_penalty ** count)
        mmr_scores.append((mmr_score, final, task_score, sym_id))
        file_counts[file_path] = count + 1
    mmr_scores.sort(reverse=True)
    seeds = mmr_scores[:40]

    for mmr_score, seed_final, _, seed_id in seeds:
        for edge in incoming.get(seed_id, []):
            source = edge.get('source')
            if edge.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                add(source, seed_final * 0.70, 'callers')
                for edge2 in incoming.get(source, []):
                    if edge2.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                        add(edge2['source'], seed_final * 0.30, 'callers_2hop')
            else:
                add(source, neighbor_score(source, seed_final, 0.35, symbols, keywords, idf, false_positive_blacklist), 'import_neighbors')
        for edge in outgoing.get(seed_id, []):
            target = edge.get('target')
            if edge.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                add(target, seed_final * 0.65, 'callees')
                for edge2 in outgoing.get(target, []):
                    if edge2.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                        add(edge2['target'], seed_final * 0.25, 'callees_2hop')
            else:
                add(target, neighbor_score(target, seed_final, 0.30, symbols, keywords, idf, false_positive_blacklist), 'import_neighbors')

    if 'bugfix' in intents or 'tests' in intents:
        task_tokens = set(keywords)
        for sym in graph.get('symbols', []):
            file_path = sym.get('file', '').lower()
            if 'test' not in file_path and 'spec' not in file_path:
                continue
            overlap = task_tokens & symbol_tokens(sym)
            if overlap:
                test_score = 3.0 + len(overlap) if 'tests' in intents else 1.2 + (len(overlap) * 0.5)
                add(sym['id'], test_score, 'tests')

    symbols_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sym in graph.get('symbols', []):
        symbols_by_file[sym.get('file', '')].append(sym)
    mapped_test_files: Set[str] = set()
    for _, seed_final, _, seed_id in seeds:
        seed_sym = symbols.get(seed_id)
        if not seed_sym:
            continue
        for test_pattern in _find_test_counterparts(seed_sym.get('file', '')):
            if test_pattern in mapped_test_files:
                continue
            mapped_test_files.add(test_pattern)
            for test_sym in symbols_by_file.get(test_pattern, []):
                if test_sym['id'] not in candidates:
                    add(test_sym['id'], seed_final * 0.50, 'code_test_map')

    # ─── Type-Aware Context Expansion ──────────────────────────────────
    type_candidate_names = set()
    for item in list(candidates.values()):
        tier = item.get('context_tier', 'support')
        if tier in ('critical', 'workflow'):
            sig = item.get('signature', '')
            if sig:
                words = set(re.findall(r'\b[A-Za-z_]\w*\b', sig))
                for w in words:
                    if w not in ('Result', 'Option', 'String', 'Vec', 'Box', 'Promise', 'List', 'Map', 'Set', 'Dict', 'Any'):
                        type_candidate_names.add(w)

    if type_candidate_names:
        for sym in graph.get('symbols', []):
            kind = str(sym.get('kind', '')).lower()
            if kind in ('struct', 'class', 'interface', 'enum', 'type'):
                if sym['name'] in type_candidate_names and sym['id'] not in candidates:
                    add(sym['id'], 0.85, 'type_dependency')

    if not candidates:
        for sym in graph.get('symbols', [])[:80]:
            if is_generic_type_symbol(sym):
                continue
            add(sym['id'], float(sym.get('rank', 0)) * 0.5, 'global_fallback')

    selected = sorted(
        candidates.values(),
        key=lambda s: (
            {'critical': 3, 'workflow': 2, 'support': 1}.get(s.get('context_tier', 'support'), 1),
            s.get('selection_score', 0),
            s.get('value_per_token', 0),
            s.get('rank', 0),
        ),
        reverse=True,
    )

    def _read_sym_snippet(sym):
        return read_symbol_snippet(read_snippet_fn[0], read_snippet_fn[1], sym) if read_snippet_fn else ""

    for item in selected:
        tc = symbol_token_cost(item, token_counter, read_snippet_fn=_read_sym_snippet if read_snippet_fn else None)
        item['token_cost'] = tc
        item['value_per_token'] = round(float(item.get('selection_score', 0)) / max(1, tc), 6)

    if max_tokens > 0:
        selected.sort(
            key=lambda s: s.get('value_per_token', 0),
            reverse=True,
        )
        greedy_selected = []
        used_tokens = 0
        cut_ids: List[str] = []
        for item in selected:
            cost = item.get('token_cost', 1)
            if used_tokens + cost <= max_tokens:
                greedy_selected.append(item)
                used_tokens += cost
            else:
                cut_ids.append(item['id'])
        selected = greedy_selected
        report['omitted_by_budget'] = len(cut_ids)
        if cut_ids:
            report['budget_recommendation'] = (
                f"WARNING: {len(cut_ids)} relevant symbols were omitted due to budget limit ({max_tokens} tokens). "
                f"Consider increasing your budget profile (e.g. to 'deep' or 'generous') or allocating more tokens."
            )
    else:
        selected.sort(
            key=lambda s: (
                {'critical': 3, 'workflow': 2, 'support': 1}.get(s.get('context_tier', 'support'), 1),
                s.get('selection_score', 0),
                s.get('value_per_token', 0),
                s.get('rank', 0),
            ),
            reverse=True,
        )
        cut_ids = []
    file_limits = {'critical': 3, 'workflow': 2, 'support': 1}
    file_counts_final: Dict[str, int] = defaultdict(int)
    filtered = []
    for s in selected:
        tier = s.get('context_tier', 'support')
        f = s.get('file', '')
        limit = file_limits.get(tier, 1)
        if file_counts_final[f] < limit:
            filtered.append(s)
            file_counts_final[f] += 1
    selected = filtered
    report['selected_candidates'] = len(selected)

    # Cap test/spec symbols to 30% of selected to avoid saturation
    test_syms = [
        s for s in selected
        if any(r in s.get('selection_reasons', []) for r in ('tests', 'code_test_map'))
    ]
    if len(test_syms) > len(selected) * 0.30:
        test_syms.sort(key=lambda s: s.get('selection_score', 0))
        to_remove = len(test_syms) - max(1, int(len(selected) * 0.30))
        remove_ids = {s['id'] for s in test_syms[:to_remove]}
        selected = [s for s in selected if s['id'] not in remove_ids]
        report['test_symbols_capped'] = len(remove_ids)

    # Layer 1 — Confidence calibration
    all_scores = [c.get('selection_score', 0) for c in candidates.values()]
    min_score = min(all_scores) if all_scores else 0.0
    max_score = max(all_scores) if all_scores else 1.0
    score_range = max_score - min_score if max_score > min_score else 1.0
    total_selected = max(1, len(selected))
    for idx, item in enumerate(selected):
        raw = item.get('selection_score', 0)
        score_norm = (raw - min_score) / score_range
        rank_score = 1.0 - (idx / total_selected)
        blend = 0.55 * score_norm + 0.45 * rank_score
        item['confidence_score'] = round(blend, 4)
        if blend >= 0.65:
            item['confidence_label'] = 'very_high'
        elif blend >= 0.35:
            item['confidence_label'] = 'high'
        elif blend >= 0.10:
            item['confidence_label'] = 'medium'
        else:
            item['confidence_label'] = 'low'
        reasons = item.get('selection_reasons', [])
        overlap = item.get('task_token_overlap', [])
        parts: List[str] = []
        if overlap:
            parts.append(f"keywords: {', '.join(overlap[:5])}")
        role_labels = {
            'entry_point': 'entry point', 'api_surface': 'highly consumed API',
            'hub': 'structural hub', 'leaf': 'leaf node', 'utility': 'internal utility',
        }
        role = item.get('role', '')
        if role and role in role_labels:
            parts.append(f"role: {role_labels[role]}")
        elif role:
            parts.append(f"role: {role}")
        if item.get('exported'):
            parts.append('exported (public API)')
        if reasons:
            parts.append(f"selected as: {', '.join(reasons)}")
        item['relevance_summary'] = ' | '.join(parts) if parts else 'structural match'

    # Layer 2 — Context subgraph relations
    selected_ids = {s['id'] for s in selected}
    subgraph_edge_count = 0
    for item in selected:
        calls: List[str] = []
        called_by: List[str] = []
        imports: List[str] = []
        dep_calls: List[str] = []
        dep_called_by: List[str] = []

        for edge in outgoing.get(item['id'], []):
            tid = edge.get('target', '')
            if tid in selected_ids:
                kind = edge.get('kind', '')
                if kind in ('calls-symbol', 'calls-symbol-local') and tid not in calls:
                    calls.append(tid)
                elif kind in ('imports-symbol', 'import') and tid not in imports:
                    imports.append(tid)
                subgraph_edge_count += 1
                # 2-hop transitive calls
                for edge2 in outgoing.get(tid, []):
                    t2 = edge2.get('target', '')
                    if t2 in selected_ids and t2 != item['id'] and t2 not in calls and t2 not in dep_calls:
                        if edge2.get('kind', '') in ('calls-symbol', 'calls-symbol-local'):
                            dep_calls.append(t2)

        for edge in incoming.get(item['id'], []):
            tid = edge.get('source', '')
            if tid in selected_ids:
                kind = edge.get('kind', '')
                if kind in ('calls-symbol', 'calls-symbol-local') and tid not in called_by:
                    called_by.append(tid)
                # 2-hop transitive callers
                for edge2 in incoming.get(tid, []):
                    t2 = edge2.get('source', '')
                    if t2 in selected_ids and t2 != item['id'] and t2 not in called_by and t2 not in dep_called_by:
                        if edge2.get('kind', '') in ('calls-symbol', 'calls-symbol-local'):
                            dep_called_by.append(t2)

        item['relations'] = {
            'calls': calls, 'called_by': called_by, 'imports': imports,
            'dep_calls': dep_calls, 'dep_called_by': dep_called_by,
        }
    n = len(selected)
    density = (subgraph_edge_count / (n * (n - 1))) if n > 1 else 0.0
    report['subgraph_nodes'] = n
    report['subgraph_edges'] = subgraph_edge_count
    report['subgraph_density'] = round(density, 4)

    # Layer 3 — Smart expansion frontier
    expansion_plan: List[Dict[str, Any]] = []
    frontier_candidates: Dict[str, Dict[str, Any]] = {}
    for item in selected:
        item_score = item.get('selection_score', 0)
        for edge in outgoing.get(item['id'], []):
            tid = edge.get('target', '')
            if tid not in selected_ids and tid not in cut_ids:
                continue
            if tid in frontier_candidates:
                continue
            sym = symbols.get(tid)
            if not sym:
                continue
            kind = edge.get('kind', '')
            edge_factor = 0.75 if 'call' in kind else 0.30
            frontier_candidates[tid] = {
                'id': tid, 'score': round(item_score * edge_factor, 4),
                'reason': f"{'called by' if 'call' in kind else 'connected to'} {item['name']}",
                'tier': context_tier(sym, keywords, intents),
            }
        for edge in incoming.get(item['id'], []):
            sid = edge.get('source', '')
            if sid not in selected_ids and sid not in cut_ids:
                continue
            if sid in frontier_candidates:
                continue
            sym = symbols.get(sid)
            if not sym:
                continue
            kind = edge.get('kind', '')
            edge_factor = 0.75 if 'call' in kind else 0.30
            frontier_candidates[sid] = {
                'id': sid, 'score': round(item_score * edge_factor, 4),
                'reason': f"{'calls' if 'call' in kind else 'imports'} {item['name']}",
                'tier': context_tier(sym, keywords, intents),
            }
    expansion_plan = sorted(
        frontier_candidates.values(),
        key=lambda e: (e.get('score', 0), e.get('tier', '')),
        reverse=True,
    )[:8]
    report['expansion_plan'] = expansion_plan
    report['expansion_count'] = len(expansion_plan)
    direct_matches = report.get('direct_matches', 0)
    fallback = report.get('global_fallback', 0)
    # Degraded mode: no symbol matched the task directly. Output is then built
    # from neighbours and/or a global fallback, which is rarely what the user
    # wants. Surface this explicitly so formatters can warn at the top of the
    # generated file instead of silently shipping irrelevant context.
    report['degraded'] = direct_matches == 0 and (fallback > 0 or len(selected) == 0)
    if direct_matches == 0:
        focus_tokens_set = set(keywords)
        project_tokens = set()
        for sym in graph.get('symbols', []):
            project_tokens |= symbol_tokens(sym)
        missing = focus_tokens_set - project_tokens
        if missing:
            report['relevance_warning'] = (
                f"Task keywords {sorted(missing)} not found in project symbols. "
                f"Project may not contain relevant code for this task."
            )
        elif not report.get('relevance_warning'):
            # Matches were filtered (noise/weak/isolated) or the task only hit
            # files, not symbols. Give the user something actionable regardless.
            report['relevance_warning'] = (
                "No symbols matched the task directly; context was built from "
                "neighbours and/or global fallback. Verify the task wording or "
                "check that the relevant code is reachable from the graph."
            )
    elif selected:
        task_domain_keywords = set()
        for kw in keywords:
            if kw in ('auth', 'authentication', 'login', 'payment', 'email', 'search', 'cache', 'order'):
                task_domain_keywords.add(kw)
        if task_domain_keywords:
            matched_domain = False
            for sym in selected:
                name_lower = sym.get('name', '').lower()
                file_lower = sym.get('file', '').lower()
                for dk in task_domain_keywords:
                    if dk in name_lower or dk in file_lower:
                        matched_domain = True
                        break
                if matched_domain:
                    break
            if not matched_domain:
                report['relevance_warning'] = (
                    f"Task domain keywords {sorted(task_domain_keywords)} not found in matched symbols. "
                    f"Project may not contain relevant code for this task."
                )
    return selected, report
