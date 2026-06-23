"""Output formatting: XML, JSON, Markdown precision context generation."""

import json
from typing import Any, Dict, List, Optional, Set
from xml.sax.saxutils import escape as xml_escape

from argon.engine.keywords import extract_task_keywords
from argon.engine.scorer import symbol_tokens
from argon.engine.snippets import read_contextual_snippet, read_symbol_snippet
from argon.utils.tokens import TokenCounter, resolve_precision_budget


def get_domain_safeguards(domain: str, languages: Set[str]) -> List[str]:
    rules = []
    
    # 1. Universal Guardrails (Structural Thinking)
    rules.append("STRUCTURAL THINKING: Before outputting any code, you MUST generate a '<thinking>' block analyzing: (a) Structural constraints and helper function isolation, (b) Exact mathematical formulas, signs, and types, (c) Array indexing mappings and bounds.")
    
    # 2. Scope Pinning
    if 'rs' in languages:
        rules.append("SCOPE PINNING (RUST): Do NOT rewrite entire files (especially large files like 'solver.rs'). Isolate changes by editing strictly within specified line ranges or writing standalone helper functions/closures.")
    else:
        rules.append("SCOPE PINNING: Do NOT rewrite entire source files. Isolate changes to targeted functions or write small helper functions to prevent context blowout and hallucinations.")

    # 3. Type Signatures & Indexing (General & Rust-specific)
    if 'rs' in languages:
        rules.append("TYPE SAFETY (RUST): Rust is extremely strict on type signatures (e.g., DVector, BTreeMap, HashMap, Complex). Explicitly map variable types and check memory borrowing/ownership rules before coding.")

    # 4. Domain-Specific (Circuit Simulation / Calculator / Scientific Computing)
    is_simulation = (domain in ('scientific_computing', 'calculator') or 
                     any(t in domain.lower() for t in ('sim', 'circuit', 'solver', 'math')))
    
    if is_simulation:
        rules.append("NUMERICAL DAMPING (pnjlim): When evaluating candidate residues f(x_cand) during Newton-Raphson line searches, make sure to deactivate temporary limiting/damping (like pnjlim) in candidate states; otherwise, you will mask divergence and fail KCL convergence.")
        rules.append("MNA STAMPS CONSISTENCY: Ensure exact mathematical signs and physical dimensions. For Trapezoidal integration (TRAP) of inductors, conductance G_eq = h / (2 * L) and current source I_eq = i_L(t_n) + G_eq * v_L(t_n). Check dimensional units (Amperes) to avoid inversion errata.")
        rules.append("SPICE INDEXING CONVENTION: In SPICE/MNA matrices, Ground (Node 0) is reference and usually handled separately. Check if node solutions (0-indexed active nodes) map differently from full node voltage vectors (1-indexed, with 0 as Tierra).")
    
    return rules


def precision_symbol_block(symbol: Dict[str, Any], output_format: str, root: str, parser, keywords: List[str] = None) -> str:
    tier = symbol.get('context_tier', 'support')
    if keywords:
        snippet = read_contextual_snippet(root, parser, symbol, keywords, tier)
    else:
        snippet = read_symbol_snippet(root, parser, symbol)
    if output_format == 'compact':
        return _compact_symbol_block(symbol, snippet)
    if output_format == 'json':
        data = {
            'id': symbol.get('id', ''),
            'name': symbol.get('name', ''),
            'kind': symbol.get('kind', ''),
            'file': symbol.get('file', ''),
            'start_line': symbol.get('start_line', 0),
            'end_line': symbol.get('end_line', 0),
            'signature': symbol.get('signature', ''),
            'tier': tier,
            'role': symbol.get('role', 'module'),
            'exported': bool(symbol.get('exported')),
            'rank': symbol.get('rank', 0),
            'inbound_calls': symbol.get('inbound_calls', 0),
            'outbound_calls': symbol.get('outbound_calls', 0),
            'confidence_score': symbol.get('confidence_score'),
            'confidence_label': symbol.get('confidence_label'),
            'relevance_summary': symbol.get('relevance_summary', ''),
            'selection_reasons': symbol.get('selection_reasons', []),
            'relations': symbol.get('relations', {}),
            'code': snippet,
        }
        return json.dumps(data, ensure_ascii=False)
    if output_format == 'xml':
        conf = symbol.get('confidence_score')
        label = symbol.get('confidence_label', '')
        role = symbol.get('role', '')
        kind = symbol.get('kind', '')
        exported = 'true' if symbol.get('exported') else 'false'
        rank = symbol.get('rank', 0)
        attrs = (
            f'id="{xml_escape(symbol["id"])}" '
            f'tier="{xml_escape(tier)}" '
            f'kind="{xml_escape(kind)}" '
            f'role="{xml_escape(role)}" '
            f'exported="{exported}" '
            f'rank="{rank}" '
            f'file="{xml_escape(symbol["file"])}" line="{symbol.get("start_line", 0)}"'
        )
        if conf is not None:
            attrs += f' confidence="{conf}" label="{xml_escape(label)}"'
        relevance = symbol.get('relevance_summary', '')
        rel = symbol.get('relations', {})
        rel_parts = []
        if rel.get('calls'):
            rel_parts.append(f'  <calls>{" ".join(xml_escape(r) for r in rel["calls"])}</calls>')
        if rel.get('called_by'):
            rel_parts.append(f'  <called_by>{" ".join(xml_escape(r) for r in rel["called_by"])}</called_by>')
        if rel.get('imports'):
            rel_parts.append(f'  <imports>{" ".join(xml_escape(r) for r in rel["imports"])}</imports>')
        if rel.get('dep_calls'):
            rel_parts.append(f'  <dep_calls>{" ".join(xml_escape(r) for r in rel["dep_calls"])}</dep_calls>')
        if rel.get('dep_called_by'):
            rel_parts.append(f'  <dep_called_by>{" ".join(xml_escape(r) for r in rel["dep_called_by"])}</dep_called_by>')
        rel_block = '\n'.join(rel_parts) if rel_parts else ''
        parts = [f'  <sym {attrs}>']
        if relevance:
            parts.append(f'    <relevance>{xml_escape(relevance)}</relevance>')
        if rel_block:
            parts.append(f'    <relations>\n{rel_block}\n    </relations>')
        parts.append(f'    <sig>{xml_escape(symbol.get("signature", ""))}</sig>')
        parts.append(f'    <code><![CDATA[\n{snippet}\n]]></code>')
        parts.append(f'  </sym>')
        return '\n'.join(parts)
    return (
        f"### {symbol['id']}\n"
        f"```{symbol.get('file', '').rsplit('.', 1)[-1]}\n{snippet}\n```\n"
    )


def _compact_symbol_block(symbol: Dict[str, Any], snippet: str) -> str:
    """Token-optimized compact format. ~75% fewer tokens than XML."""
    sid = symbol.get('id', '')
    tier_abbr = symbol.get('context_tier', 'support')[:3]
    kind = symbol.get('kind', '')[:4]
    role = symbol.get('role', 'module')[:4]
    conf = round(symbol.get('confidence_score', 0) or 0, 2)
    sig = symbol.get('signature', '').replace('\n', ' ').strip()[:120]
    name = _short_id(sid)

    line = f'!{name}|{tier_abbr}|{kind}|{role}|{conf}'
    rel = symbol.get('relations', {})
    parts = [line]

    for r in rel.get('called_by', []):
        parts.append(f'  < {_short_id(r)}')
    for r in rel.get('calls', []):
        parts.append(f'  > {_short_id(r)}')
    for r in rel.get('imports', []):
        parts.append(f'  + {_short_id(r)}')
    for r in rel.get('dep_called_by', []):
        parts.append(f'  << {_short_id(r)}')
    for r in rel.get('dep_calls', []):
        parts.append(f'  >> {_short_id(r)}')

    if sig:
        parts.append(f'  sig: {sig}')
    if snippet:
        indented = '\n'.join(f'  {l}' for l in snippet.splitlines()[:80])
        parts.append(f'  code:\n{indented}')
    return '\n'.join(parts)


def _short_id(sid: str) -> str:
    """Shorten symbol ID when possible without losing uniqueness."""
    if '::' in sid:
        file_part, sym = sid.rsplit('::', 1)
        short_file = file_part.split('/')[-1]
        return f'{short_file}::{sym}'
    return sid


def build_precision_compact(
    graph: Dict[str, Any],
    task: str,
    max_tokens: int,
    selected: List[Dict[str, Any]] = None,
    selection_report: Dict[str, Any] = None,
    keywords: List[str] = None,
    root: str = '',
    parser=None,
) -> str:
    """Build token-optimized compact output for LLM consumption."""
    max_tokens, budget_settings = resolve_precision_budget(max_tokens, 'custom')
    selection_report = selection_report or {}
    keywords = keywords or extract_task_keywords(task)
    communities = graph.get('communities', {})

    header_parts = [
        f'# repo: {graph["root"]} | domain: {graph.get("project_domain", "general")}',
        f'# task: {task}',
        f'# budget: {max_tokens} | profile: {budget_settings["name"]}',
    ]
    sub = selection_report.get('subgraph_nodes', 0)
    if sub:
        header_parts.append(
            f'# subgraph: {sub}n/{selection_report.get("subgraph_edges", 0)}e '
            f'density={selection_report.get("subgraph_density", 0)}'
        )
    omitted = selection_report.get('omitted_by_budget', 0)
    if omitted:
        header_parts.append(f'# omitted: {omitted}')
    if communities:
        comm_str = ' '.join(f'[{l}]={len(fs)}' for l, fs in sorted(communities.items(), key=lambda x: -len(x[1]))[:8])
        header_parts.append(f'# modules: {comm_str}')

    debt = graph.get('debt', {})
    if debt.get('total_markers'):
        header_parts.append(f'# debt: {debt["total_markers"]} markers ({debt.get("by_severity", {}).get("high", 0)} high)')

    tg = graph.get('testing_gaps', {})
    if tg.get('coverage_ratio', 0):
        header_parts.append(f'# tests: {tg["coverage_ratio"]*100:.0f}% coverage ({tg["tested_files"]}/{tg["total_source_files"]})')

    warning = selection_report.get('relevance_warning', '')
    if warning:
        header_parts.append(f'# warning: {warning}')

    languages = {n.get('type') for n in graph.get('nodes', [])}
    rules = get_domain_safeguards(graph.get('project_domain', 'general'), languages)
    for r in rules:
        header_parts.append(f'# safeguard: {r}')

    header_parts.append('')

    counter = TokenCounter(model='gpt-4.1', strict=False)

    lines = list(header_parts)
    used_tokens = counter.count('\n'.join(lines))

    layers = precision_layers(selected) if selected else {'critical': [], 'workflow': [], 'support': []}
    tier_order = [('critical', 'crt'), ('workflow', 'wkf'), ('support', 'sup')]

    for tier_name, tier_abbr in tier_order:
        tier_symbols = layers.get(tier_name, [])
        if not tier_symbols:
            continue
        lines.append(f'# --- {tier_name} ({len(tier_symbols)}) ---')
        for sym in tier_symbols:
            block = precision_symbol_block(sym, 'compact', root, parser, keywords)
            trial = '\n'.join(lines + [block])
            if used_tokens + counter.count('\n' + block) > max_tokens:
                break
            lines.append(block)
            lines.append('')
            used_tokens = counter.count('\n'.join(lines))

    exp_plan = selection_report.get('expansion_plan', [])
    if exp_plan:
        lines.append('# expansion:')
        for ep in exp_plan[:5]:
            eid = _short_id(ep.get('id', ''))
            escore = ep.get('score', 0)
            lines.append(f'#   -> {eid} ({ep.get("tier", "sup")[:3]}, {escore:.2f})')

    output = '\n'.join(lines)
    return output


def precision_layers(symbols: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    layers = {'critical': [], 'workflow': [], 'support': []}
    for sym in symbols:
        tier = sym.get('context_tier', 'support')
        if tier not in layers:
            tier = 'support'
        layers[tier].append(sym)
    return layers


def compact_precision_symbol(sym: Dict[str, Any]) -> Dict[str, Any]:
    keep = {
        'id', 'name', 'kind', 'file', 'start_line', 'end_line', 'signature',
        'context_tier', 'selection_score', 'selection_reasons', 'task_token_overlap',
        'rank', 'inbound_calls', 'outbound_calls', 'token_cost', 'value_per_token',
    }
    return {key: value for key, value in sym.items() if key in keep}


def precision_expansion_plan(
    selected: List[Dict[str, Any]],
    full_code_ids: Set[str],
    included_ids: Set[str],
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    tier_weight = {'critical': 3, 'workflow': 2, 'support': 1}
    candidates = sorted(
        selected,
        key=lambda sym: (
            sym.get('id') not in included_ids,
            tier_weight.get(sym.get('context_tier', 'support'), 1),
            sym.get('selection_score', 0),
            sym.get('value_per_token', 0),
        ),
        reverse=True,
    )
    for sym in candidates:
        sid = sym.get('id', '')
        if not sid or sid in full_code_ids:
            continue
        tier = sym.get('context_tier', 'support')
        if sid in included_ids:
            reason = 'compact_included_expand_if_needed'
        else:
            reason = 'omitted_due_to_budget'
        if (
            tier == 'support'
            and reason == 'compact_included_expand_if_needed'
            and not sym.get('task_token_overlap')
        ):
            continue
        plan.append({
            'symbol': sid,
            'tier': tier,
            'reason': reason,
            'file': sym.get('file', ''),
            'line': sym.get('start_line', 0),
            'selection_score': sym.get('selection_score', 0),
            'value_per_token': sym.get('value_per_token', 0),
            'expand_with': f'argon_expand_symbol("{sid}")',
        })
        if len(plan) >= max_items:
            break
    return plan


def fit_expansion_plan(
    payload: Dict[str, Any],
    selected: List[Dict[str, Any]],
    max_tokens: int,
    counter: Optional['TokenCounter'] = None,
    max_items: int = 8,
) -> None:
    full_code_ids = {sym.get('id', '') for sym in payload.get('symbols', []) if sym.get('code')}
    included_ids = {sym.get('id', '') for sym in payload.get('symbols', [])}
    plan = precision_expansion_plan(selected, full_code_ids, included_ids, max_items=max_items)
    payload['expansion_plan'] = []
    for item in plan:
        trial = dict(payload)
        trial['expansion_plan'] = payload['expansion_plan'] + [item]
        trial_text = json.dumps(trial, ensure_ascii=False, indent=2)
        if counter.count(trial_text) <= max_tokens:
            payload['expansion_plan'].append(item)
            continue
        compact = {
            'symbol': item['symbol'],
            'tier': item['tier'],
            'reason': item['reason'],
            'expand_with': item['expand_with'],
        }
        trial['expansion_plan'] = payload['expansion_plan'] + [compact]
        if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= max_tokens:
            payload['expansion_plan'].append(compact)
        elif not payload['expansion_plan']:
            payload['expansion_plan'].append({
                'symbol': item['symbol'],
                'expand_with': item['expand_with'],
            })
            while counter.count(json.dumps(payload, ensure_ascii=False, indent=2)) > max_tokens:
                payload['expansion_plan'].pop()
                break
        else:
            break


def build_precision_json_payload(
    graph: Dict[str, Any],
    task: str,
    max_tokens: int,
    budget_profile: str = 'custom',
    selected: List[Dict[str, Any]] = None,
    selection_report: Dict[str, Any] = None,
    keywords: List[str] = None,
    counter: TokenCounter = None,
    root: str = '',
    parser=None,
) -> str:
    max_tokens, budget_settings = resolve_precision_budget(max_tokens, budget_profile)
    selection_report = selection_report or {}
    keywords = keywords or extract_task_keywords(task)
    omitted = 0

    languages = {n.get('type') for n in graph.get('nodes', [])}
    rules = get_domain_safeguards(graph.get('project_domain', 'general'), languages)

    payload = {
        'repo': graph['root'],
        'precision': True,
        'domain': graph.get('project_domain', 'general'),
        'task': task,
        'max_tokens': max_tokens,
        'budget_profile': budget_settings['name'],
        'warning': selection_report.get('relevance_warning', ''),
        'safeguards': rules,
        'subgraph': {
            'nodes': selection_report.get('subgraph_nodes', 0),
            'edges': selection_report.get('subgraph_edges', 0),
            'density': selection_report.get('subgraph_density', 0),
        },
        'symbols': [],
        'layers': {'critical': [], 'workflow': [], 'support': []},
        'packaging_report': {'full_code_symbols': 0, 'compact_symbols': 0, 'support_compacted_by_default': 0},
        'omitted_by_budget': selection_report.get('omitted_by_budget', 0),
        'expansion_plan': [],
    }
    if selected:
        for sym in selected:
            tier = sym.get('context_tier', 'support')
            compact = {
                'id': sym.get('id', ''),
                'name': sym.get('name', ''),
                'tier': tier,
                'file': sym.get('file', ''),
                'line': sym.get('start_line', 0),
                'signature': sym.get('signature', ''),
                'kind': sym.get('kind', ''),
                'role': sym.get('role', 'module'),
                'exported': bool(sym.get('exported')),
                'rank': sym.get('rank', 0),
                'inbound_calls': sym.get('inbound_calls', 0),
                'outbound_calls': sym.get('outbound_calls', 0),
                'confidence_score': sym.get('confidence_score'),
                'confidence_label': sym.get('confidence_label'),
                'relevance_summary': sym.get('relevance_summary', ''),
                'selection_reasons': sym.get('selection_reasons', []),
                'relations': sym.get('relations', {}),
            }
            if tier in ('critical', 'workflow'):
                compact['code'] = read_contextual_snippet(root, parser, sym, keywords, tier)
            trial = dict(payload)
            trial['symbols'] = payload['symbols'] + [compact]
            trial_text = json.dumps(trial, ensure_ascii=False)
            if counter.count(trial_text) <= max_tokens:
                payload['symbols'].append(compact)
                payload['layers'].setdefault(tier, []).append(compact['id'])
                if compact.get('code'):
                    payload['packaging_report']['full_code_symbols'] += 1
                else:
                    payload['packaging_report']['compact_symbols'] += 1
            else:
                break
    exp_plan = selection_report.get('expansion_plan', []) if selection_report else []
    if exp_plan:
        payload['expansion_plan'] = [
            {'id': e['id'], 'score': e.get('score', 0), 'tier': e.get('tier', 'support'), 'reason': e.get('reason', '')}
            for e in exp_plan[:8]
        ]
    payload['used_tokens'] = counter.count(json.dumps(payload, ensure_ascii=False))
    output = json.dumps(payload, ensure_ascii=False)
    return output


def build_precision_markdown(
    graph: Dict[str, Any],
    task: str,
    max_tokens: int,
    budget_profile: str = 'custom',
    selected: List[Dict[str, Any]] = None,
    selection_report: Dict[str, Any] = None,
    keywords: List[str] = None,
    counter: TokenCounter = None,
    root: str = '',
    parser=None,
    output_path: str = '',
) -> None:
    _generate_precision_xml_or_markdown(
        graph, task, max_tokens, budget_profile, selected, selection_report,
        keywords, counter, root, parser, output_path, 'markdown',
    )


def _generate_precision_xml_or_markdown(
    graph, task, max_tokens, budget_profile, selected, selection_report,
    keywords, counter, root, parser, output_path, output_format,
):
    max_tokens, budget_settings = resolve_precision_budget(max_tokens, budget_profile)
    selection_report = selection_report or {}
    keywords = keywords or extract_task_keywords(task)
    used_blocks: List[str] = []
    omitted = 0

    languages = {n.get('type') for n in graph.get('nodes', [])}
    rules = get_domain_safeguards(graph.get('project_domain', 'general'), languages)

    if output_format == 'xml':
        warning_attr = ''
        if selection_report.get('relevance_warning'):
            warning_attr = f' warning="{xml_escape(selection_report["relevance_warning"])}"'
        
        safeguards_xml = ""
        if rules:
            safeguards_xml = "  <safeguards>\n"
            for rule in rules:
                safeguards_xml += f"    <rule>{xml_escape(rule)}</rule>\n"
            safeguards_xml += "  </safeguards>\n"

        header = (
            f'<repo name="{xml_escape(graph["root"])}" domain="{xml_escape(graph.get("project_domain", "general"))}"{warning_attr}>\n'
            f'  <task>{xml_escape(task)}</task>\n'
            f'{safeguards_xml}'
            f'  <context>\n'
        )
        footer = '  </context>\n</repo>\n'
    else:
        warning_line = ""
        if selection_report.get('relevance_warning'):
            warning_line = f"\n**WARNING**: {selection_report['relevance_warning']}\n"
        
        safeguards_md = ""
        if rules:
            safeguards_md = "\n## AI CODING SAFEGUARDS\n"
            for rule in rules:
                safeguards_md += f"- {rule}\n"
            safeguards_md += "\n"

        header = (
            f"# {graph['root']} [{graph.get('project_domain', 'general')}] — {task}\n"
            f"{warning_line}"
            f"{safeguards_md}"
        )
        footer = ''

    budget = max_tokens - counter.count(header + footer)
    used = 0
    layers = precision_layers(selected or [])
    included_ids: Set[str] = set()
    for tier in ('critical', 'workflow', 'support'):
        tier_symbols = layers[tier]
        if not tier_symbols:
            continue
        if output_format == 'xml':
            section_open = f'    <layer name="{tier}">\n'
            section_close = f'    </layer>'
        else:
            section_open = f"\n## {tier.upper()}\n"
            section_close = ""
        section_cost = counter.count(section_open + section_close)
        if used + section_cost <= budget:
            used_blocks.append(section_open.rstrip("\n"))
            used += section_cost
        else:
            omitted += len(tier_symbols)
            continue
        for sym in tier_symbols:
            if tier == 'support':
                sig = sym.get('signature', '')
                block = (
                    f'  <sym id="{xml_escape(sym["id"])}" tier="support" file="{xml_escape(sym["file"])}" line="{sym.get("start_line", 0)}" sig="{xml_escape(sig)}" />'
                    if output_format == 'xml'
                    else f"- {sym['id']}: `{sig}`\n"
                )
            else:
                block = precision_symbol_block(sym, output_format, root, parser, keywords)
            cost = counter.count(block)
            if used + cost <= budget:
                used_blocks.append(block)
                used += cost
                included_ids.add(sym['id'])
            else:
                compact = dict(sym)
                compact.pop('code', None)
                compact_block = (
                    json.dumps(compact, ensure_ascii=False)
                    if output_format == 'json'
                    else f'  <symbol-ref id="{xml_escape(sym["id"])}" file="{xml_escape(sym["file"])}" line="{sym.get("start_line", 0)}" />'
                    if output_format == 'xml'
                    else f"- {sym['id']} ({sym['file']}:{sym.get('start_line', 0)})\n"
                )
                compact_cost = counter.count(compact_block)
                if used + compact_cost <= budget:
                    used_blocks.append(compact_block)
                    used += compact_cost
                    included_ids.add(sym['id'])
                else:
                    omitted += 1
        if section_close:
            used_blocks.append(section_close)

    if output_format == 'xml':
        output = header + "\n".join(used_blocks) + "\n" + footer
    else:
        output = header + "\n".join(used_blocks)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f"[+] Precision context: {output_path} | {counter.count(output)} tokens")


def generate_precision_context(
    graph: Dict[str, Any],
    output_path: str,
    task: str,
    max_tokens: int = 4096,
    output_format: str = 'xml',
    budget_profile: str = 'custom',
    selected: List[Dict[str, Any]] = None,
    selection_report: Dict[str, Any] = None,
    keywords: List[str] = None,
    counter: TokenCounter = None,
    root: str = '',
    parser=None,
) -> None:
    max_tokens, budget_settings = resolve_precision_budget(max_tokens, budget_profile)
    output_format = output_format.lower()
    if output_format not in {'xml', 'json', 'markdown', 'compact'}:
        raise ValueError("--format must be one of: xml, json, markdown, compact")

    if output_format == 'json':
        output = build_precision_json_payload(
            graph, task, max_tokens, budget_profile,
            selected, selection_report, keywords, counter, root, parser,
        )
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[+] Precision context: {output_path} | {counter.count(output)} tokens")
        return

    if output_format == 'compact':
        output = build_precision_compact(
            graph, task, max_tokens,
            selected=selected, selection_report=selection_report,
            keywords=keywords, root=root, parser=parser
        )
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[+] Precision compact: {output_path} | {counter.count(output)} tokens")
        return

    _generate_precision_xml_or_markdown(
        graph, task, max_tokens, budget_profile, selected, selection_report,
        keywords, counter, root, parser, output_path, output_format,
    )
