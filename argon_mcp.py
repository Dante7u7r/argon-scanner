#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON MCP v2.0 -- MODEL CONTEXT PROTOCOL SERVER
-------------------------------------------------
Token-budgeted queries. La IA llama solo lo que necesita.
Nuevo: argon_focused_context para contexto por tarea.
"""

import sys
import json
import os
from collections import Counter
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("[!] Dependencia faltante: mcp\n    pip install mcp\n", file=sys.stderr)
    sys.exit(1)

try:
    from argon import ArgonEngine, estimate_tokens
except ImportError:
    print("[!] Error: No se encontró argon.py.", file=sys.stderr)
    sys.exit(1)

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
    Contexto enfocado para una tarea específica. Analiza la descripción,
    busca archivos relevantes por keywords, y devuelve solo lo necesario
    dentro del budget de tokens. Equivalente al --map-tokens de Aider.

    Args:
        task_description: Qué vas a hacer (ej: 'refactor authentication flow').
        max_tokens: Budget de tokens para la respuesta (default: 4096).
    """
    graph = _load_graph()
    if not graph:
        return _no_graph_msg()

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
def argon_rescan(project_path: str = ".") -> str:
    """
    Regenera el grafo. Úsalo tras cambios estructurales.

    Args:
        project_path: Ruta del proyecto (default: directorio actual).
    """
    global _GRAPH_CACHE, _GRAPH_PATH
    try:
        abs_path = os.path.abspath(project_path)
        engine = ArgonEngine(abs_path)
        graph = engine.build_graph()

        # Output siempre en la raíz del proyecto escaneado
        graph_path = os.path.join(abs_path, 'argon_graph.json')
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
        engine.generate_context_report(graph, os.path.join(abs_path, 'ARGON.md'))

        _GRAPH_CACHE = None
        _GRAPH_PATH = graph_path

        s = graph['stats']
        return f"✓ Updated: {s['total_files']} files, {s['total_connections']} connections.\nParser: {graph.get('parser_mode', 'regex')}\nOutput: {abs_path}"
    except Exception as e:
        return f"Error: {e}"


if __name__ == '__main__':
    graph = _load_graph()
    if graph is None:
        print("[!] Grafo no encontrado. La IA puede usar argon_rescan().", file=sys.stderr)
    else:
        print(f"[+] ARGON MCP v2.0 listo. {graph['stats']['total_files']} archivos.", file=sys.stderr)
    mcp.run()
