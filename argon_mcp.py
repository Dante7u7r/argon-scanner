#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON MCP v3.0 -- MODEL CONTEXT PROTOCOL SERVER
-------------------------------------------------
Token-budgeted queries. Usa Precision context cuando el grafo lo soporta.
"""

import sys
import json
import os
from collections import Counter
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argon_deps import ensure as _ensure_dep

_mcp_mod = _ensure_dep("mcp", "mcp", description="MCP server protocol")
if _mcp_mod is None:
    print("[!] No se pudo instalar 'mcp'. Ejecuta: pip install mcp", file=sys.stderr)
    sys.exit(1)
from mcp.server.fastmcp import FastMCP

try:
    from argon import ArgonEngine, TokenCounter, estimate_tokens
except ImportError:
    print("[!] Error: No se encontró argon.py.", file=sys.stderr)
    sys.exit(1)

try:
    from argon_laravel import laravel_overview, laravel_routes, laravel_schema, laravel_recent_errors
except ImportError:
    laravel_overview = laravel_routes = laravel_schema = laravel_recent_errors = None

try:
    from argon_semantic import SemanticIndex
    _HAS_SEMANTIC = True
except ImportError:
    SemanticIndex = None
    _HAS_SEMANTIC = False

mcp = FastMCP(
    name="argon",
    instructions=(
        "ARGON es un escáner de arquitectura de proyectos. "
        "Usa sus herramientas para entender la estructura del código sin leer cada archivo. "
        "Flujo: argon_overview() → argon_focused_context(tarea) → argon_query/deps si necesitas más. "
        "Todas las herramientas respetan un budget de tokens para no saturar el contexto."
    )
)

_GRAPH_CACHE: Optional[dict] = None
_GRAPH_PATH = os.path.join(os.getcwd(), 'argon_graph.json')
_SEMANTIC_INDEX = None
_SEMANTIC_GRAPH_MTIME: Optional[float] = None


def _load_graph() -> Optional[dict]:
    global _GRAPH_CACHE, _GRAPH_PATH
    try:
        mtime = os.path.getmtime(_GRAPH_PATH)
        if _GRAPH_CACHE is not None and _GRAPH_CACHE.get('_mtime') == mtime:
            return _GRAPH_CACHE
        with open(_GRAPH_PATH, 'r', encoding='utf-8') as f:
            _GRAPH_CACHE = json.load(f)
            _GRAPH_CACHE['_mtime'] = mtime
        return _GRAPH_CACHE
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        return None


def _no_graph_msg() -> str:
    return f"⚠️ Grafo no disponible.\nEjecuta: python argon.py . --context\nBuscando en: {_GRAPH_PATH}"


def _truncate(text: str, max_tokens: int) -> str:
    """Truncate text to fit within token budget."""
    tokens = estimate_tokens(text)
    if tokens <= max_tokens:
        return text
    # Cut at ~max_tokens * 4 chars
    limit = max_tokens * 4
    return text[:limit] + f"\n\n[TRUNCATED — showing ~{max_tokens} of ~{tokens} tokens]"


def _graph_root_dir() -> str:
    return os.path.dirname(os.path.abspath(_GRAPH_PATH)) or os.getcwd()


def _precision_context_json(graph: dict, task_description: str, max_tokens: int, model: str) -> str:
    engine = ArgonEngine(_graph_root_dir(), precision=False, model=model)
    selected = engine._select_precision_symbols(graph, task_description)
    selection_report = getattr(engine, '_last_selection_report', {})
    counter = TokenCounter(model=model, strict=False)
    payload = {
        'repository': graph.get('root', ''),
        'precision': True,
        'task': task_description,
        'model': model,
        'max_tokens': max_tokens,
        'used_tokens': 0,
        'stats': graph.get('stats', {}),
        'selection_report': selection_report,
        'symbols': [],
        'omitted_symbols': 0,
    }
    full_snippet_budget = int(max_tokens * 0.72)
    omitted = 0
    for sym in selected:
        full = dict(sym)
        full['code'] = engine._read_symbol_snippet(sym)
        compact = dict(sym)
        current_tokens = counter.count(json.dumps(payload, ensure_ascii=False, indent=2))
        if current_tokens < full_snippet_budget:
            trial = dict(payload)
            trial['symbols'] = payload['symbols'] + [full]
            trial['omitted_symbols'] = omitted
            if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= full_snippet_budget:
                payload['symbols'].append(full)
                continue
        trial = dict(payload)
        trial['symbols'] = payload['symbols'] + [compact]
        trial['omitted_symbols'] = omitted
        if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= max_tokens:
            payload['symbols'].append(compact)
        else:
            omitted += 1

    payload['omitted_symbols'] = omitted
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    payload['used_tokens'] = counter.count(output)
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    while counter.count(output) > max_tokens and payload['symbols']:
        payload['symbols'].pop()
        payload['omitted_symbols'] += 1
        payload['used_tokens'] = 0
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        payload['used_tokens'] = counter.count(output)
        output = json.dumps(payload, ensure_ascii=False, indent=2)
    return output


def _json(data: object, max_tokens: int = 4096, model: str = "gpt-4.1") -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    counter = TokenCounter(model=model, strict=False)
    if counter.count(text) <= max_tokens:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data["truncated"] = True
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return _truncate(text, max_tokens)


def _symbol_maps(graph: dict):
    symbols = {s.get('id'): s for s in graph.get('symbols', [])}
    incoming = {}
    outgoing = {}
    for edge in graph.get('symbol_edges', []):
        src = edge.get('source')
        dst = edge.get('target')
        if src and dst:
            outgoing.setdefault(src, []).append(edge)
            incoming.setdefault(dst, []).append(edge)
    return symbols, incoming, outgoing


def _find_symbol_id(graph: dict, query: str) -> Optional[str]:
    q = query.lower()
    for sym in graph.get('symbols', []):
        sid = sym.get('id', '')
        if sid.lower() == q or sym.get('name', '').lower() == q:
            return sid
    for sym in graph.get('symbols', []):
        sid = sym.get('id', '')
        if q in sid.lower() or q in sym.get('name', '').lower():
            return sid
    return None


# =========================================================================
# TOOLS
# =========================================================================

@mcp.tool()
def argon_overview(max_tokens: int = 2048) -> str:
    """
    Resumen de alto nivel: estadísticas, tipos de archivo, archivos principales,
    y hubs de conectividad. Úsalo al inicio para orientarte.

    Args:
        max_tokens: Máximo de tokens en la respuesta (default: 2048).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()

    nodes = graph['nodes']
    stats = graph['stats']

    top = sorted(nodes, key=lambda n: n.get('importance', 0), reverse=True)[:15]
    type_dist = Counter(n['type'] for n in nodes)
    type_str = '  '.join(f"{t.upper()}:{c}" for t, c in type_dist.most_common(10))

    edge_count: Counter = Counter()
    for e in graph.get('edges', []):
        edge_count[e['source']] += 1
        edge_count[e['target']] += 1
    hubs = edge_count.most_common(5)

    out = [
        f"PROJECT: {graph['root']}",
        f"FILES: {stats['total_files']}  |  CONNECTIONS: {stats['total_connections']}",
        f"PARSER: {graph.get('parser_mode', 'regex')}",
        f"SCANNED: {stats['timestamp']}",
        "",
        "TOP FILES (by importance):",
        *[f"  [{n.get('importance',0):.2f}] {n['id']} [{n['lines']}L | {len(n.get('symbols',[]))} syms]"
          + (f"\n    > {n['summary'][:80]}" if n.get('summary') else '')
          for n in top],
        "",
        f"FILE TYPES: {type_str}",
    ]

    if hubs:
        out += ["", "HUBS (high connectivity):"]
        out += [f"  {path} ({cnt} connections)" for path, cnt in hubs]

    return _truncate("\n".join(out), max_tokens)


@mcp.tool()
def argon_query(symbol: str, max_tokens: int = 1024) -> str:
    """
    Busca un símbolo (clase, función, etc.) en el grafo.

    Args:
        symbol: Nombre del símbolo (parcial o exacto).
        max_tokens: Máximo de tokens (default: 1024).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()

    q = symbol.lower()
    results = []
    for node in graph['nodes']:
        for sym in node.get('symbols', []):
            if q in sym['name'].lower():
                results.append({
                    'file': node['id'], 'name': sym['name'],
                    'kind': sym['kind'], 'line': sym['line'],
                    'summary': node.get('summary', ''),
                })

    if not results:
        return f"Symbol '{symbol}' not found."

    out = [f"RESULTS for '{symbol}' ({len(results)} found):"]
    for r in results[:15]:
        out.append(f"  [{r['kind'].upper():6}] {r['name']}  →  {r['file']}:{r['line']}")
        if r['summary']:
            out.append(f"           > {r['summary'][:60]}")

    if len(results) > 15:
        out.append(f"  ... +{len(results) - 15} more.")
    return _truncate("\n".join(out), max_tokens)


@mcp.tool()
def argon_deps(file_path: str, max_tokens: int = 1024) -> str:
    """
    Dependencias de un archivo: qué importa y quién lo importa.

    Args:
        file_path: Nombre o ruta parcial del archivo.
        max_tokens: Máximo de tokens (default: 1024).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()

    q = file_path.lower().replace('\\', '/')
    node = next((n for n in graph['nodes'] if q in n['id'].lower()), None)

    if not node:
        suggestions = [n['id'] for n in graph['nodes'] if q.split('/')[-1] in n['id'].lower()][:5]
        msg = f"File '{file_path}' not found."
        if suggestions:
            msg += "\nDid you mean:\n" + "\n".join(f"  {s}" for s in suggestions)
        return msg

    outgoing = [e['target'] for e in graph['edges'] if e['source'] == node['id']]
    incoming = [e['source'] for e in graph['edges'] if e['target'] == node['id']]

    syms = node.get('symbols', [])
    sym_str = ', '.join(f"{s['kind']}:{s['name']}" for s in syms[:15])

    out = [
        f"FILE: {node['id']}",
        f"TYPE: {node['type'].upper()} | LINES: {node['lines']} | IMPORTANCE: {node.get('importance', 0):.2f}",
        f"SYMBOLS: {sym_str or 'none'}",
    ]
    if node.get('summary'):
        out.append(f"SUMMARY: {node['summary']}")
    out += [
        "", f"IMPORTS ({len(outgoing)}):",
        *([f"  → {t}" for t in outgoing] or ["  (none)"]),
        "", f"IMPORTED BY ({len(incoming)}):",
        *([f"  ← {s}" for s in incoming] or ["  (none — entry point or leaf)"]),
    ]
    return _truncate("\n".join(out), max_tokens)


@mcp.tool()
def argon_search(keyword: str, max_tokens: int = 1024) -> str:
    """
    Busca archivos por concepto/funcionalidad en paths, summaries y símbolos.

    Args:
        keyword: Concepto a buscar (ej: 'auth', 'payment', 'cache').
        max_tokens: Máximo de tokens (default: 1024).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()

    q = keyword.lower()
    results = []
    for node in graph['nodes']:
        score = 0
        reasons = []
        if q in node['id'].lower():
            score += 3; reasons.append('path')
        if q in node.get('summary', '').lower():
            score += 2; reasons.append('summary')
        matching = [s['name'] for s in node.get('symbols', []) if q in s['name'].lower()]
        if matching:
            score += len(matching); reasons.append(f"sym:{','.join(matching[:3])}")
        if any(q in i.lower() for i in node.get('imports', [])):
            score += 1; reasons.append('imports')
        if score > 0:
            results.append((score, node, reasons))

    results.sort(key=lambda x: x[0], reverse=True)
    if not results:
        return f"No files related to '{keyword}'."

    out = [f"FILES for '{keyword}' ({len(results)} found):"]
    for score, node, reasons in results[:15]:
        out.append(f"  [{score:2}pts] {node['id']}  ({', '.join(reasons)})")
        if node.get('summary'):
            out.append(f"         > {node['summary'][:60]}")
    if len(results) > 15:
        out.append(f"  ... +{len(results) - 15} more.")
    return _truncate("\n".join(out), max_tokens)


@mcp.tool()
def argon_focused_context(task_description: str, max_tokens: int = 4096) -> str:
    """
    Contexto enfocado para una tarea específica. Si el grafo es Precision,
    usa el selector semántico de ArgonEngine; si no, usa fallback por archivos.

    Args:
        task_description: Qué vas a hacer (ej: 'refactor authentication flow').
        max_tokens: Budget de tokens para la respuesta (default: 4096).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    if graph.get('precision') and graph.get('symbols'):
        return _precision_context_json(graph, task_description, max_tokens, graph.get('model', 'gpt-4.1'))

    # Extract keywords from task description
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                  'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                  'and', 'or', 'not', 'but', 'if', 'then', 'else', 'when',
                  'this', 'that', 'it', 'i', 'we', 'you', 'they', 'do', 'does',
                  'did', 'will', 'would', 'should', 'could', 'can', 'may',
                  'need', 'want', 'make', 'add', 'fix', 'update', 'change',
                  'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en',
                  'con', 'por', 'para', 'que', 'como', 'es', 'son', 'hay',
                  'quiero', 'necesito', 'hacer', 'crear', 'modificar', 'arreglar'}
    words = set(task_description.lower().split()) - stop_words
    keywords = [w for w in words if len(w) > 2]

    if not keywords:
        keywords = task_description.lower().split()[:5]

    # Phase 2: Build semantic boost map if available
    semantic_boost: Dict[str, float] = {}
    if _HAS_SEMANTIC and SemanticIndex is not None and graph.get('symbols'):
        global _SEMANTIC_INDEX, _SEMANTIC_GRAPH_MTIME
        graph_mtime = graph.get('_mtime')
        if _SEMANTIC_INDEX is None or _SEMANTIC_GRAPH_MTIME != graph_mtime:
            _SEMANTIC_INDEX = SemanticIndex()
            _SEMANTIC_INDEX.build_from_graph(graph)
            _SEMANTIC_GRAPH_MTIME = graph_mtime
        sem_results = _SEMANTIC_INDEX.query(task_description, top_k=30)
        for sem_score, sym in sem_results:
            file_id = sym.get('file', '')
            if file_id:
                semantic_boost[file_id] = max(semantic_boost.get(file_id, 0), sem_score * 5.0)

    # Score all files against keywords
    scored = []
    for node in graph['nodes']:
        score = 0
        for kw in keywords:
            if kw in node['id'].lower():
                score += 3
            if kw in node.get('summary', '').lower():
                score += 2
            if any(kw in s['name'].lower() for s in node.get('symbols', [])):
                score += 2
            if any(kw in i.lower() for i in node.get('imports', [])):
                score += 1
        # Boost by importance
        score += node.get('importance', 0) * 2
        # Phase 2: Semantic boost
        score += semantic_boost.get(node['id'], 0)
        if score > 0:
            scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return f"No relevant files found for: {task_description}"

    # Build context within budget
    header = f"FOCUSED CONTEXT for: {task_description}\nKeywords: {', '.join(keywords)}\nMatched: {len(scored)} files\n\n"
    budget = max_tokens - estimate_tokens(header)
    used = 0
    blocks = []

    for score, node in scored:
        lines = [f"### {node['id']} [score:{score:.1f} | {node['lines']}L]"]
        if node.get('summary'):
            lines.append(f"> {node['summary']}")
        syms = node.get('symbols', [])
        if syms:
            sym_str = ', '.join(f"{s['kind']}:{s['name']}" for s in syms[:15])
            lines.append(f"SYMBOLS: {sym_str}")
        imps = node.get('imports', [])
        if imps:
            lines.append(f"DEPENDS: {', '.join(imps[:8])}")
        lines.append("")

        block = "\n".join(lines)
        cost = estimate_tokens(block)
        if used + cost > budget:
            break
        blocks.append(block)
        used += cost

    return header + "\n".join(blocks) + f"\n[~{used + estimate_tokens(header)} tokens used of {max_tokens} budget]"


@mcp.tool()
def argon_precision_context(task_description: str, max_tokens: int = 4096, model: str = "gpt-4.1") -> str:
    """
    Contexto precision basado en symbol graph cuando el grafo fue generado con --precision.
    Devuelve XML compacto con símbolos rankeados, líneas y firmas.

    Args:
        task_description: Tarea a resolver.
        max_tokens: Budget real si tiktoken está instalado.
        model: Modelo para conteo de tokens.
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    if not graph.get('precision') or not graph.get('symbols'):
        return "Precision graph not available. Run: python argon.py . --precision --task \"...\""

    return _precision_context_json(graph, task_description, max_tokens, model)


@mcp.tool()
def argon_rescan(
    project_path: str = ".",
    precision: bool = False,
    model: str = "gpt-4.1",
    task: str = "general repository understanding",
    max_tokens: int = 4096,
    output_format: str = "json",
) -> str:
    """
    Regenera el grafo. Úsalo tras cambios estructurales.

    Args:
        project_path: Ruta del proyecto (default: directorio actual).
    """
    global _GRAPH_CACHE, _GRAPH_PATH
    try:
        abs_path = os.path.abspath(project_path)
        engine = ArgonEngine(abs_path, precision=precision, model=model)
        graph = engine.build_graph()

        # Output siempre en la raíz del proyecto escaneado
        graph_path = os.path.join(abs_path, 'argon_graph.json')
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
        if precision:
            ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md'}.get(output_format, 'json')
            engine.generate_precision_context(
                graph,
                os.path.join(abs_path, f'ARGON_PRECISION.{ext}'),
                task=task,
                max_tokens=max_tokens,
                output_format=output_format if output_format in {'xml', 'json', 'markdown'} else 'json',
            )
        else:
            engine.generate_context_report(graph, os.path.join(abs_path, 'ARGON.md'), max_tokens=max_tokens)

        _GRAPH_CACHE = None
        _GRAPH_PATH = graph_path

        s = graph['stats']
        return (
            f"✓ Updated: {s['total_files']} files, {s['total_connections']} connections.\n"
            f"Symbols: {s.get('total_symbols', 0)} | Symbol calls: {s.get('total_symbol_calls', 0)} | "
            f"Unresolved: {s.get('unresolved_imports', 0)}\n"
            f"Parser: {graph.get('parser_mode', 'regex')} | Precision: {graph.get('precision', False)}\n"
            f"Output: {abs_path}"
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def argon_find_related(query: str, max_tokens: int = 2048) -> str:
    """Devuelve símbolos relacionados por imports/calls para un símbolo o fragmento."""
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    sid = _find_symbol_id(graph, query)
    if not sid:
        return f"Symbol '{query}' not found."
    symbols, incoming, outgoing = _symbol_maps(graph)
    related = []
    for edge in incoming.get(sid, []) + outgoing.get(sid, []):
        other_id = edge['source'] if edge.get('target') == sid else edge.get('target')
        related.append({
            "symbol": other_id,
            "name": symbols.get(other_id, {}).get("name", ""),
            "file": symbols.get(other_id, {}).get("file", ""),
            "relation": edge.get("kind"),
            "direction": "incoming" if edge.get('target') == sid else "outgoing",
        })
    return _json({"query": query, "symbol": sid, "related": related}, max_tokens)


@mcp.tool()
def argon_trace_callers(symbol: str, max_tokens: int = 2048) -> str:
    """Lista callers directos de un símbolo en el grafo Precision."""
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    sid = _find_symbol_id(graph, symbol)
    if not sid:
        return f"Symbol '{symbol}' not found."
    symbols, incoming, _ = _symbol_maps(graph)
    callers = [
        {"symbol": e["source"], "file": symbols.get(e["source"], {}).get("file", ""), "local": e.get("local")}
        for e in incoming.get(sid, [])
        if e.get("kind") == "calls-symbol"
    ]
    return _json({"symbol": sid, "callers": callers}, max_tokens)


@mcp.tool()
def argon_trace_callees(symbol: str, max_tokens: int = 2048) -> str:
    """Lista callees directos de un símbolo en el grafo Precision."""
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    sid = _find_symbol_id(graph, symbol)
    if not sid:
        return f"Symbol '{symbol}' not found."
    symbols, _, outgoing = _symbol_maps(graph)
    callees = [
        {"symbol": e["target"], "file": symbols.get(e["target"], {}).get("file", ""), "local": e.get("local")}
        for e in outgoing.get(sid, [])
        if e.get("kind") == "calls-symbol"
    ]
    return _json({"symbol": sid, "callees": callees}, max_tokens)


@mcp.tool()
def argon_context_for_symbol(symbol: str, max_tokens: int = 2048, model: str = "gpt-4.1") -> str:
    """Devuelve snippet y relaciones directas para un símbolo."""
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    sid = _find_symbol_id(graph, symbol)
    if not sid:
        return f"Symbol '{symbol}' not found."
    symbols, incoming, outgoing = _symbol_maps(graph)
    engine = ArgonEngine(_graph_root_dir(), precision=False, model=model)
    sym = dict(symbols[sid])
    sym["code"] = engine._read_symbol_snippet(sym)
    sym["incoming"] = incoming.get(sid, [])[:20]
    sym["outgoing"] = outgoing.get(sid, [])[:20]
    return _json(sym, max_tokens, model=model)


@mcp.tool()
def argon_framework_overview(max_tokens: int = 2048) -> str:
    """Detecta framework conocido y devuelve resumen. Actualmente soporta Laravel."""
    if laravel_overview is None:
        return "Laravel adapter unavailable."
    data = {"laravel": laravel_overview(_graph_root_dir())}
    return _json(data, max_tokens)


@mcp.tool()
def argon_laravel_routes(max_tokens: int = 4096) -> str:
    """Rutas Laravel detectadas estáticamente."""
    if laravel_routes is None:
        return "Laravel adapter unavailable."
    return _json({"routes": laravel_routes(_graph_root_dir())}, max_tokens)


@mcp.tool()
def argon_laravel_schema(max_tokens: int = 4096) -> str:
    """Schema Laravel inferido desde migrations."""
    if laravel_schema is None:
        return "Laravel adapter unavailable."
    return _json({"schema": laravel_schema(_graph_root_dir())}, max_tokens)


@mcp.tool()
def argon_recent_errors(max_tokens: int = 4096) -> str:
    """Errores recientes conocidos por adapters. Actualmente lee storage/logs/laravel.log."""
    if laravel_recent_errors is None:
        return "Laravel adapter unavailable."
    return _json({"laravel": laravel_recent_errors(_graph_root_dir())}, max_tokens)


# =========================================================================
# PHASE 2: SEMANTIC SEARCH
# =========================================================================

@mcp.tool()
def argon_semantic_search(query: str, top_k: int = 15, max_tokens: int = 2048) -> str:
    """
    Búsqueda semántica de símbolos por intención/concepto.
    Usa embeddings locales para encontrar símbolos por significado,
    no solo por coincidencia de palabras clave.

    Args:
        query: Concepto o intención (ej: 'cómo se guardan los usuarios', 'payment processing').
        top_k: Máximo de resultados (default: 15).
        max_tokens: Budget de tokens (default: 2048).
    """
    if not _HAS_SEMANTIC:
        return "Semantic search unavailable. Install: pip install sentence-transformers (optional, TF-IDF fallback also works)"

    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    if not graph.get('symbols'):
        return "No symbols in graph. Run: python argon.py . --precision"

    global _SEMANTIC_INDEX, _SEMANTIC_GRAPH_MTIME
    graph_mtime = graph.get('_mtime')
    if _SEMANTIC_INDEX is None or _SEMANTIC_GRAPH_MTIME != graph_mtime:
        _SEMANTIC_INDEX = SemanticIndex()
        _SEMANTIC_INDEX.build_from_graph(graph)
        _SEMANTIC_GRAPH_MTIME = graph_mtime

    results = _SEMANTIC_INDEX.query(query, top_k=top_k)
    if not results:
        return f"No semantic matches for: '{query}'"

    out = [f"SEMANTIC SEARCH: '{query}' (backend: {_SEMANTIC_INDEX.backend_name}, {len(results)} results):"]
    for score, sym in results:
        out.append(
            f"  [{score:.3f}] {sym.get('id', '')}  ({sym.get('kind', '')})\n"
            f"           file: {sym.get('file', '')}:{sym.get('start_line', 0)}"
        )
        if sym.get('signature'):
            out.append(f"           sig: {sym['signature'][:80]}")
    return _truncate("\n".join(out), max_tokens)


# =========================================================================
# PHASE 4: AST QUERY
# =========================================================================

@mcp.tool()
def argon_ast_query(pattern: str, kind: str = "", max_tokens: int = 2048) -> str:
    """
    Busca símbolos por patrón en su firma/nombre. Permite encontrar
    métodos por tipo de retorno, parámetros, o patrones de código.

    Args:
        pattern: Regex o texto a buscar en firmas y nombres (ej: 'Promise<User>', 'async.*save').
        kind: Filtrar por tipo de símbolo: func, class, interface, etc. (vacío = todos).
        max_tokens: Budget de tokens (default: 2048).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()
    if not graph.get('symbols'):
        return "No symbols in graph. Run: python argon.py . --precision"

    import re as _re
    try:
        pat = _re.compile(pattern, _re.IGNORECASE)
    except _re.error as e:
        return f"Invalid regex pattern: {e}"

    kind_filter = kind.lower().strip() if kind else ''
    results = []
    for sym in graph['symbols']:
        if kind_filter and sym.get('kind', '').lower() != kind_filter:
            continue
        searchable = f"{sym.get('name', '')} {sym.get('signature', '')}"
        if pat.search(searchable):
            results.append(sym)

    if not results:
        return f"No symbols matching pattern '{pattern}'" + (f" (kind={kind})" if kind else "")

    out = [f"AST QUERY: /{pattern}/ {f'kind={kind} ' if kind else ''}({len(results)} matches):"]
    for sym in results[:20]:
        out.append(
            f"  [{sym.get('kind', ''):8}] {sym.get('name', '')}  →  {sym.get('file', '')}:{sym.get('start_line', 0)}\n"
            f"             sig: {sym.get('signature', '')[:100]}"
        )
    if len(results) > 20:
        out.append(f"  ... +{len(results) - 20} more.")
    return _truncate("\n".join(out), max_tokens)


def main() -> None:
    graph = _load_graph()
    if graph is None:
        print("[!] Grafo no encontrado. La IA puede usar argon_rescan().", file=sys.stderr)
    else:
        print(f"[+] ARGON MCP v3.0 listo. {graph['stats']['total_files']} archivos.", file=sys.stderr)
    mcp.run()


if __name__ == '__main__':
    main()
