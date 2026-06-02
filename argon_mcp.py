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
import inspect
from collections import Counter
from typing import Any, Dict, List, Optional

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

_TOOL_NAMES = [
    "argon_overview", "argon_query", "argon_deps", "argon_search",
    "argon_focused_context", "argon_precision_context", "argon_context_layer",
    "argon_rescan", "argon_find_related", "argon_trace_callers",
    "argon_trace_callees", "argon_context_for_symbol", "argon_expand_symbol",
    "argon_framework_overview", "argon_laravel_routes", "argon_laravel_schema",
    "argon_recent_errors", "argon_semantic_search", "argon_ast_query",
    "argon_smart_start", "argon_deep_dive",
]


class ArgonMCPServer:
    """MCP server for the ARGON architecture scanner."""

    def __init__(self, project_path: str = "."):
        self.project_path = os.path.abspath(project_path)
        self._graph_cache: Optional[dict] = None
        self._graph_path = os.path.join(self.project_path, 'argon_graph.json')
        self._semantic_index = None
        self._semantic_graph_mtime: Optional[float] = None
        self._has_semantic = False
        self._semantic_cls = None
        self._init_laravel()
        self._init_semantic()
        self.mcp = FastMCP(
            name="argon",
            instructions=(
                "ARGON es un escáner de arquitectura de proyectos. "
                "Usa sus herramientas para entender la estructura del código sin leer cada archivo. "
                "Flujo: argon_overview() → argon_focused_context(tarea) → argon_query/deps si necesitas más. "
                "Todas las herramientas respetan un budget de tokens para no saturar el contexto."
            )
        )
        self._register_tools()

    def _init_laravel(self) -> None:
        try:
            from argon_laravel import (
                laravel_overview, laravel_routes, laravel_schema,
                laravel_recent_errors,
            )
            self._laravel_overview = laravel_overview
            self._laravel_routes = laravel_routes
            self._laravel_schema = laravel_schema
            self._laravel_recent_errors = laravel_recent_errors
        except ImportError:
            self._laravel_overview = self._laravel_routes = self._laravel_schema = self._laravel_recent_errors = None

    def _init_semantic(self) -> None:
        try:
            from argon_semantic import SemanticIndex
            self._semantic_cls = SemanticIndex
            self._has_semantic = True
        except ImportError:
            self._semantic_cls = None
            self._has_semantic = False

    def _register_tools(self) -> None:
        for name in _TOOL_NAMES:
            method = getattr(self, name)
            self.mcp.tool(name=name)(method)

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------

    def _load_graph(self) -> Optional[dict]:
        try:
            mtime = os.path.getmtime(self._graph_path)
            if self._graph_cache is not None and self._graph_cache.get('_mtime') == mtime:
                return self._graph_cache
            with open(self._graph_path, 'r', encoding='utf-8') as f:
                self._graph_cache = json.load(f)
                self._graph_cache['_mtime'] = mtime
            return self._graph_cache
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"[!] Error: {e}", file=sys.stderr)
            return None

    def _no_graph_msg(self) -> str:
        return f"⚠️ Grafo no disponible.\nEjecuta: python argon.py . --context\nBuscando en: {self._graph_path}"

    def _truncate(self, text: str, max_tokens: int) -> str:
        tokens = estimate_tokens(text)
        if tokens <= max_tokens:
            return text
        limit = max_tokens * 4
        return text[:limit] + f"\n\n[TRUNCATED — showing ~{max_tokens} of ~{tokens} tokens]"

    def _graph_root_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self._graph_path)) or os.getcwd()

    def _precision_context_json(
        self, graph: dict, task_description: str, max_tokens: int,
        model: str, budget_profile: str = "custom",
    ) -> str:
        engine = ArgonEngine(self._graph_root_dir(), precision=False, model=model)
        return engine._build_precision_json_payload(graph, task_description, max_tokens, budget_profile)

    def _precision_layer_payload(
        self, graph: dict, task_description: str, tier: str,
        max_tokens: int, model: str, include_code: bool = True,
    ) -> str:
        allowed = {'critical', 'workflow', 'support'}
        requested = tier.lower().strip()
        if requested == 'all':
            tiers = ['critical', 'workflow', 'support']
        elif requested in allowed:
            tiers = [requested]
        else:
            return f"Invalid tier '{tier}'. Use: critical, workflow, support, all."

        engine = ArgonEngine(self._graph_root_dir(), precision=False, model=model)
        selected = engine._select_precision_symbols(graph, task_description)
        counter = TokenCounter(model=model, strict=False)
        payload: Dict[str, Any] = {
            'repository': graph.get('root', ''),
            'task': task_description,
            'tier': requested,
            'model': model,
            'max_tokens': max_tokens,
            'used_tokens': 0,
            'selection_report': getattr(engine, '_last_selection_report', {}),
            'layers': {name: [] for name in tiers},
            'omitted_symbols': 0,
        }

        omitted = 0
        for sym in selected:
            sym_tier = sym.get('context_tier', 'support')
            if sym_tier not in tiers:
                continue
            item = dict(sym)
            if include_code and sym_tier != 'support':
                item['code'] = engine._read_symbol_snippet(sym)
            elif sym_tier == 'support':
                item = engine._compact_precision_symbol(sym)
            trial = dict(payload)
            trial_layers = {name: list(items) for name, items in payload['layers'].items()}
            trial_layers.setdefault(sym_tier, []).append(item)
            trial['layers'] = trial_layers
            trial['omitted_symbols'] = omitted
            if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= max_tokens:
                payload['layers'].setdefault(sym_tier, []).append(item)
            else:
                compact = dict(item)
                compact.pop('code', None)
                trial_layers = {name: list(items) for name, items in payload['layers'].items()}
                trial_layers.setdefault(sym_tier, []).append(compact)
                trial['layers'] = trial_layers
                if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= max_tokens:
                    payload['layers'].setdefault(sym_tier, []).append(compact)
                else:
                    omitted += 1

        payload['omitted_symbols'] = omitted
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        payload['used_tokens'] = counter.count(output)
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        return self._truncate(output, max_tokens)

    def _json(self, data: object, max_tokens: int = 4096, model: str = "gpt-4.1") -> str:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        counter = TokenCounter(model=model, strict=False)
        if counter.count(text) <= max_tokens:
            return text
        if isinstance(data, dict):
            data = dict(data)
            data["truncated"] = True
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return self._truncate(text, max_tokens)

    @staticmethod
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

    @staticmethod
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

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def argon_overview(self, max_tokens: int = 2048) -> str:
        """Resumen de alto nivel: estadísticas, tipos de archivo, archivos principales,
        y hubs de conectividad. Úsalo al inicio para orientarte. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()

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

        return self._truncate("\n".join(out), max_tokens)

    def argon_query(self, symbol: str, max_tokens: int = 1024) -> str:
        """Busca un símbolo (clase, función, etc.) en el grafo. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()

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
            out.append(f"  [{r['kind'].upper():6}] {r['name']}  ->  {r['file']}:{r['line']}")
            if r['summary']:
                out.append(f"           > {r['summary'][:60]}")

        if len(results) > 15:
            out.append(f"  ... +{len(results) - 15} more.")
        return self._truncate("\n".join(out), max_tokens)

    def argon_deps(self, file_path: str, max_tokens: int = 1024) -> str:
        """Dependencias de un archivo: qué importa y quién lo importa. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()

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
            *([f"  -> {t}" for t in outgoing] or ["  (none)"]),
            "", f"IMPORTED BY ({len(incoming)}):",
            *([f"  <- {s}" for s in incoming] or ["  (none -- entry point or leaf)"]),
        ]
        return self._truncate("\n".join(out), max_tokens)

    def argon_search(self, keyword: str, max_tokens: int = 1024) -> str:
        """Busca archivos por concepto/funcionalidad en paths, summaries y símbolos. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()

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
        return self._truncate("\n".join(out), max_tokens)

    def argon_focused_context(self, task_description: str, max_tokens: int = 4096) -> str:
        """Contexto enfocado para una tarea específica. Si el grafo es Precision,
        usa el selector semántico de ArgonEngine; si no, usa fallback por archivos. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        if graph.get('precision') and graph.get('symbols'):
            return self._precision_context_json(graph, task_description, max_tokens, graph.get('model', 'gpt-4.1'))

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

        semantic_boost: Dict[str, float] = {}
        if self._has_semantic and self._semantic_cls is not None and graph.get('symbols'):
            graph_mtime = graph.get('_mtime')
            if self._semantic_index is None or self._semantic_graph_mtime != graph_mtime:
                self._semantic_index = self._semantic_cls()
                self._semantic_index.build_from_graph(graph)
                self._semantic_graph_mtime = graph_mtime
            sem_results = self._semantic_index.query(task_description, top_k=30)
            for sem_score, sym in sem_results:
                file_id = sym.get('file', '')
                if file_id:
                    semantic_boost[file_id] = max(semantic_boost.get(file_id, 0), sem_score * 5.0)

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
            score += node.get('importance', 0) * 2
            score += semantic_boost.get(node['id'], 0)
            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return f"No relevant files found for: {task_description}"

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

    def argon_precision_context(
        self, task_description: str, max_tokens: int = 4096,
        model: str = "gpt-4.1", budget_profile: str = "custom",
    ) -> str:
        """Contexto precision basado en symbol graph cuando el grafo fue generado con --precision.
        Devuelve XML compacto con símbolos rankeados, líneas y firmas. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        if not graph.get('precision') or not graph.get('symbols'):
            return "Precision graph not available. Run: python argon.py . --precision --task \"...\""

        return self._precision_context_json(graph, task_description, max_tokens, model, budget_profile)

    def argon_context_layer(
        self, task_description: str, tier: str = "critical",
        max_tokens: int = 2048, model: str = "gpt-4.1", include_code: bool = True,
    ) -> str:
        """Devuelve solo una capa del contexto Precision para ahorrar tokens. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        if not graph.get('precision') or not graph.get('symbols'):
            return "Precision graph not available. Run: python argon.py . --precision --task \"...\""
        return self._precision_layer_payload(graph, task_description, tier, max_tokens, model, include_code)

    def argon_rescan(
        self, project_path: str = ".", precision: bool = False,
        model: str = "gpt-4.1", task: str = "general repository understanding",
        max_tokens: int = 4096, output_format: str = "json",
        budget_profile: str = "custom",
    ) -> str:
        """Regenera el grafo. Úsalo tras cambios estructurales. """
        try:
            abs_path = os.path.abspath(project_path)
            engine = ArgonEngine(abs_path, precision=precision, model=model)
            graph = engine.build_graph()

            graph_path = os.path.join(abs_path, 'argon_graph.json')
            with open(graph_path, 'w', encoding='utf-8') as f:
                json.dump(graph, f, indent=2, ensure_ascii=False)
            if precision:
                ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md'}.get(output_format, 'json')
                engine.generate_precision_context(
                    graph, os.path.join(abs_path, f'ARGON_PRECISION.{ext}'),
                    task=task, max_tokens=max_tokens,
                    output_format=output_format if output_format in {'xml', 'json', 'markdown'} else 'json',
                    budget_profile=budget_profile,
                )
            else:
                engine.generate_context_report(graph, os.path.join(abs_path, 'ARGON.md'), max_tokens=max_tokens)

            self._graph_cache = None
            self._graph_path = graph_path
            self.project_path = abs_path

            s = graph['stats']
            return (
                f"* Updated: {s['total_files']} files, {s['total_connections']} connections.\n"
                f"Symbols: {s.get('total_symbols', 0)} | Symbol calls: {s.get('total_symbol_calls', 0)} | "
                f"Unresolved: {s.get('unresolved_imports', 0)}\n"
                f"Parser: {graph.get('parser_mode', 'regex')} | Precision: {graph.get('precision', False)}\n"
                f"Output: {abs_path}"
            )
        except Exception as e:
            return f"Error: {e}"

    def argon_find_related(self, query: str, max_tokens: int = 2048) -> str:
        """Devuelve símbolos relacionados por imports/calls para un símbolo o fragmento. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        sid = self._find_symbol_id(graph, query)
        if not sid:
            return f"Symbol '{query}' not found."
        symbols, incoming, outgoing = self._symbol_maps(graph)
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
        return self._json({"query": query, "symbol": sid, "related": related}, max_tokens)

    def argon_trace_callers(self, symbol: str, max_tokens: int = 2048) -> str:
        """Lista callers directos de un símbolo en el grafo Precision. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        sid = self._find_symbol_id(graph, symbol)
        if not sid:
            return f"Symbol '{symbol}' not found."
        symbols, incoming, _ = self._symbol_maps(graph)
        callers = [
            {"symbol": e["source"], "file": symbols.get(e["source"], {}).get("file", ""), "local": e.get("local")}
            for e in incoming.get(sid, [])
            if e.get("kind") == "calls-symbol"
        ]
        return self._json({"symbol": sid, "callers": callers}, max_tokens)

    def argon_trace_callees(self, symbol: str, max_tokens: int = 2048) -> str:
        """Lista callees directos de un símbolo en el grafo Precision. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        sid = self._find_symbol_id(graph, symbol)
        if not sid:
            return f"Symbol '{symbol}' not found."
        symbols, _, outgoing = self._symbol_maps(graph)
        callees = [
            {"symbol": e["target"], "file": symbols.get(e["target"], {}).get("file", ""), "local": e.get("local")}
            for e in outgoing.get(sid, [])
            if e.get("kind") == "calls-symbol"
        ]
        return self._json({"symbol": sid, "callees": callees}, max_tokens)

    def argon_context_for_symbol(self, symbol: str, max_tokens: int = 2048, model: str = "gpt-4.1") -> str:
        """Devuelve snippet y relaciones directas para un símbolo. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        sid = self._find_symbol_id(graph, symbol)
        if not sid:
            return f"Symbol '{symbol}' not found."
        symbols, incoming, outgoing = self._symbol_maps(graph)
        engine = ArgonEngine(self._graph_root_dir(), precision=False, model=model)
        sym = dict(symbols[sid])
        sym["code"] = engine._read_symbol_snippet(sym)
        sym["incoming"] = incoming.get(sid, [])[:20]
        sym["outgoing"] = outgoing.get(sid, [])[:20]
        return self._json(sym, max_tokens, model=model)

    def argon_expand_symbol(self, symbol: str, max_tokens: int = 2048, model: str = "gpt-4.1") -> str:
        """Expande un símbolo concreto con código y relaciones directas.
        Alias explícito para flujos incrementales. """
        return self.argon_context_for_symbol(symbol, max_tokens=max_tokens, model=model)

    def argon_framework_overview(self, max_tokens: int = 2048) -> str:
        """Detecta framework conocido y devuelve resumen. Actualmente soporta Laravel. """
        if self._laravel_overview is None:
            return "Laravel adapter unavailable."
        data = {"laravel": self._laravel_overview(self._graph_root_dir())}
        return self._json(data, max_tokens)

    def argon_laravel_routes(self, max_tokens: int = 4096) -> str:
        """Rutas Laravel detectadas estáticamente. """
        if self._laravel_routes is None:
            return "Laravel adapter unavailable."
        return self._json({"routes": self._laravel_routes(self._graph_root_dir())}, max_tokens)

    def argon_laravel_schema(self, max_tokens: int = 4096) -> str:
        """Schema Laravel inferido desde migrations. """
        if self._laravel_schema is None:
            return "Laravel adapter unavailable."
        return self._json({"schema": self._laravel_schema(self._graph_root_dir())}, max_tokens)

    def argon_recent_errors(self, max_tokens: int = 4096) -> str:
        """Errores recientes conocidos por adapters. Actualmente lee storage/logs/laravel.log. """
        if self._laravel_recent_errors is None:
            return "Laravel adapter unavailable."
        return self._json({"laravel": self._laravel_recent_errors(self._graph_root_dir())}, max_tokens)

    # ------------------------------------------------------------------
    # Semantic / AST tools
    # ------------------------------------------------------------------

    def argon_semantic_search(self, query: str, top_k: int = 15, max_tokens: int = 2048) -> str:
        """Búsqueda semántica de símbolos por intención/concepto. """
        if not self._has_semantic:
            return ("Semantic search unavailable. Install: pip install sentence-transformers "
                    "(optional, TF-IDF fallback also works)")

        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        if not graph.get('symbols'):
            return "No symbols in graph. Run: python argon.py . --precision"

        graph_mtime = graph.get('_mtime')
        if self._semantic_index is None or self._semantic_graph_mtime != graph_mtime:
            self._semantic_index = self._semantic_cls()
            self._semantic_index.build_from_graph(graph)
            self._semantic_graph_mtime = graph_mtime

        results = self._semantic_index.query(query, top_k=top_k)
        if not results:
            return f"No semantic matches for: '{query}'"

        out = [f"SEMANTIC SEARCH: '{query}' (backend: {self._semantic_index.backend_name}, {len(results)} results):"]
        for score, sym in results:
            out.append(
                f"  [{score:.3f}] {sym.get('id', '')}  ({sym.get('kind', '')})\n"
                f"           file: {sym.get('file', '')}:{sym.get('start_line', 0)}"
            )
            if sym.get('signature'):
                out.append(f"           sig: {sym['signature'][:80]}")
        return self._truncate("\n".join(out), max_tokens)

    def argon_ast_query(self, pattern: str, kind: str = "", max_tokens: int = 2048) -> str:
        """Busca símbolos por patrón en su firma/nombre. Permite encontrar
        métodos por tipo de retorno, parámetros, o patrones de código. """
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
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
                f"  [{sym.get('kind', ''):8}] {sym.get('name', '')}  ->  {sym.get('file', '')}:{sym.get('start_line', 0)}\n"
                f"             sig: {sym.get('signature', '')[:100]}"
            )
        if len(results) > 20:
            out.append(f"  ... +{len(results) - 20} more.")
        return self._truncate("\n".join(out), max_tokens)

    def argon_smart_start(self, task: str) -> str:
        """
        Quick check: does this project have code relevant to the task?
        Uses cached graph only — no re-scan. Returns relevance assessment in <100 tokens.
        Call this BEFORE spending tokens on full context generation.

        Args:
            task: What you're trying to accomplish (e.g., 'fix auth bug', 'add payment webhook').
        """
        from argon.engine.keywords import extract_task_keywords
        from argon.engine.scorer import symbol_tokens as _st
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()

        keywords = extract_task_keywords(task)
        all_symbols = graph.get('symbols', [])
        if not all_symbols:
            return "Project has 0 parsed symbols. Run argon_rescan() first."

        matched = 0
        total = len(all_symbols)
        project_tokens = set()
        for sym in all_symbols[:5000]:
            project_tokens |= _st(sym)

        matched_kw = [kw for kw in keywords if kw in project_tokens]
        matched = sum(1 for sym in all_symbols if any(kw in sym.get('name', '').lower() or kw in sym.get('file', '').lower() for kw in keywords))

        ratio = matched / max(1, total)
        if ratio > 0.05:
            level = 'HIGH'
            advice = 'Use argon_focused_context() to get relevant files.'
        elif ratio > 0.01 or matched_kw:
            level = 'MEDIUM'
            advice = 'Some keywords found. Use argon_focused_context() with --budget-profile micro first.'
        else:
            level = 'LOW'
            advice = f'Keywords {matched_kw or keywords[:5]} not found in project symbols. The project may not have relevant code. Try rephrasing the task or use argon_rescan().'

        debt = graph.get('debt', {})
        tg = graph.get('testing_gaps', {})
        communities = graph.get('communities', {})
        return (
            f'RELEVANCE: {level} ({matched} of {total} symbols match)\n'
            f'Matched keywords: {matched_kw[:8] or "none"}\n'
            f'Modules: {len(communities)} detected\n'
            f'Debt: {debt.get("total_markers", 0)} markers ({debt.get("by_severity", {}).get("high", 0)} high)\n'
            f'Test coverage: {tg.get("coverage_ratio", 0)*100:.0f}%\n'
            f'\n{advice}'
        )

    def argon_deep_dive(self, symbol: str, max_tokens: int = 4096) -> str:
        """
        Deep-dive into a symbol with code, direct callers/callees, and transitive dependency chains.
        Use this after argon_focused_context() to understand a specific symbol in depth.

        Args:
            symbol: Symbol ID or name (e.g., 'authenticate' or 'auth.ts::authenticate').
            max_tokens: Token budget (default: 4096).
        """
        import json as _json
        graph = self._load_graph()
        if not graph:
            return self._no_graph_msg()
        sid = self._find_symbol_id(graph, symbol)
        if not sid:
            return f"Symbol '{symbol}' not found."

        symbols, incoming, outgoing = self._symbol_maps(graph)
        sym = dict(symbols.get(sid, {}))
        if not sym:
            return f"Symbol '{sid}' has no data."

        engine = ArgonEngine(self._graph_root_dir(), precision=False, model='gpt-4.1')
        sym['code'] = engine._read_symbol_snippet(sym)

        # Direct relations
        direct_callers = []
        for e in incoming.get(sid, []):
            if e.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                cs = symbols.get(e['source'], {})
                direct_callers.append({'id': e['source'], 'name': cs.get('name', ''), 'file': cs.get('file', '')})
        direct_callees = []
        for e in outgoing.get(sid, []):
            if e.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                cs = symbols.get(e['target'], {})
                direct_callees.append({'id': e['target'], 'name': cs.get('name', ''), 'file': cs.get('file', '')})

        # Transitive chains (2-hop)
        trans_callers = []
        for c in direct_callers:
            for e in incoming.get(c['id'], []):
                if e.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                    cs = symbols.get(e['source'], {})
                    trans_callers.append({'id': e['source'], 'name': cs.get('name', ''), 'via': c['name']})
        trans_callees = []
        for c in direct_callees:
            for e in outgoing.get(c['id'], []):
                if e.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                    cs = symbols.get(e['target'], {})
                    trans_callees.append({'id': e['target'], 'name': cs.get('name', ''), 'via': c['name']})

        result = {
            'symbol': sid,
            'name': sym.get('name', ''),
            'kind': sym.get('kind', ''),
            'role': sym.get('role', ''),
            'file': sym.get('file', ''),
            'line': sym.get('start_line', 0),
            'signature': sym.get('signature', ''),
            'rank': sym.get('rank', 0),
            'code': sym['code'][:3000],
            'relations': {
                'callers': direct_callers[:15],
                'callees': direct_callees[:15],
                'transitive_callers': trans_callers[:10],
                'transitive_callees': trans_callees[:10],
            }
        }
        return self._truncate(_json.dumps(result, ensure_ascii=False, indent=2), max_tokens)

    # ------------------------------------------------------------------
    # JSON-RPC protocol (parallel to FastMCP stdio)
    # ------------------------------------------------------------------

    def _json_schema_for_tool(self, func) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for name, param in inspect.signature(func).parameters.items():
            annotation = param.annotation
            schema_type = "string"
            if annotation is int:
                schema_type = "integer"
            elif annotation is bool:
                schema_type = "boolean"
            properties[name] = {"type": schema_type}
            if param.default is inspect._empty:
                required.append(name)
        return {"type": "object", "properties": properties, "required": required}

    def _tool_definitions(self) -> List[Dict[str, Any]]:
        tools = []
        for name in _TOOL_NAMES:
            func = getattr(self, name)
            tools.append({
                "name": name,
                "description": inspect.getdoc(func) or "",
                "inputSchema": self._json_schema_for_tool(func),
            })
        return tools

    def _handle_jsonrpc(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        msg_id = message.get("id")

        if msg_id is None:
            return None

        try:
            if method == "initialize":
                params = message.get("params") or {}
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "argon", "version": "3.0"},
                        "instructions": self.mcp.instructions,
                    },
                }
            if method == "ping":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": self._tool_definitions()}}
            if method == "tools/call":
                params = message.get("params") or {}
                name = params.get("name")
                args = params.get("arguments") or {}
                if name not in _TOOL_NAMES:
                    raise ValueError(f"Unknown tool: {name}")
                result = getattr(self, name)(**args)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": str(result)}], "isError": False},
                }
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def _run_stdio_jsonrpc(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                response = self._handle_jsonrpc(json.loads(line))
            except Exception as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)

    def run(self) -> None:
        graph = self._load_graph()
        if graph is None:
            print("[!] Grafo no encontrado. La IA puede usar argon_rescan().", file=sys.stderr)
        else:
            print(f"[+] ARGON MCP v3.0 listo. {graph['stats']['total_files']} archivos.", file=sys.stderr)
        self._run_stdio_jsonrpc()


def main() -> None:
    server = ArgonMCPServer()
    server.run()


if __name__ == '__main__':
    main()
