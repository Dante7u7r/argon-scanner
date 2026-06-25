import argparse
import json
import os

from argon import pathspec, tiktoken, ts_pack
from argon.engine.graph import PRECISION_BUDGET_PROFILES, ArgonEngine

LLM_GUIDE = """
╔════════════════════════════════════════════════════════════════════╗
║                    ARGON — Quick Guide for LLMs                    ║
╠════════════════════════════════════════════════════════════════════╣
║  ARGON scans codebases and returns token-budgeted context.        ║
║  No ML/LLMs at scan time — pure static analysis (tree-sitter).    ║
╚═════════════════════════════════════════════════════════════════════╝

RECOMMENDED FLOW:
  1. argon . --smart-start
     → Returns: domain, symbol count, relevance yes/no.
     → If "not relevant": STOP, don't waste tokens.

  2. argon . --precision --task "your task" --budget-profile micro --format compact
     → micro=1500 tokens, standard=4096, deep=8192
     → compact = 58% less tokens than JSON

  3. Read output. Look for:
     !id|tier|kind|role|confidence
     tier: cri (critical), wkf (workflow), sup (support)
     confidence: very_high≥0.65, high≥0.35, medium≥0.10, low<0.10
     > = calls, < = called by, >> = transitive calls

  4. Need more? argon expand-symbol "file.py::symbol" --max-tokens 2000

KEY FLAGS:
  --precision           Enable task-aware selection + real token counting
  --task "..."          Your task description (drives keyword scoring)
  --budget-profile      micro|standard|deep (overrides --budget)
  --format compact      Best for LLM consumption (dense, token-efficient)
  --smart-start         Check relevance before spending tokens

EXAMPLES:
  # Check if project has auth code
  argon . --smart-start

  # Get context for bug fix (1500 tokens)
  argon . --precision --task "fix login timeout" --budget-profile micro --format compact

  # Deep dive with full code (8192 tokens)
  argon . --precision --task "refactor payment flow" --budget-profile deep --format json

  # Expand a symbol with full code + relationships
  argon expand-symbol "solver.rs::total_im_sq" --max-tokens 2000

  # Visualize in browser
  argon . --precision --task "..." --view --open-view

OUTPUT LEGEND (compact):
  !table.py::_calc|cri|func|hub|0.85
    < table.py::Table              ← called by Table
    << export.py::print_table      ←← transitively called by
    >> table.py::render_row        →→ transitively calls
    sig: def _calc(...)
    code: ...

CONFIDENCE:
  very_high (≥0.65) → read code
  high (≥0.35)      → read code
  medium (≥0.10)    → skim
  low (<0.10)       → ignore

WARNINGS:
  "Task domain keywords not found" → your task keywords don't match project symbols.
  Try different task wording or check smart-start first.
"""

def _smart_start_cmd(args):
    """Quick check if project has relevant code for a task."""
    from argon import pathspec, tiktoken, ts_pack
    try:
        engine = ArgonEngine(
            args.path,
            precision=True,
            model=args.model,
            output_dir='',
            ts_pack=ts_pack,
            tiktoken_mod=tiktoken,
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        return

    graph = engine.build_graph()
    
    # Extract domain and stats
    s = graph.get('stats', {})
    symbols = []
    for node in graph.get('nodes', []):
        for sym in node.get('symbols', []):
            symbols.append(sym)
    
    # Simple keyword extraction from task if provided
    task = args.task or ""
    
    print(f"SMART START")
    print(f"  Project: {os.path.basename(os.path.abspath(args.path))}")
    print(f"  Files: {s.get('total_files', 0)} | Symbols: {s.get('total_symbols', 0)}")
    print(f"  Connections: {s.get('total_connections', 0)} | Symbol connections: {s.get('total_symbol_connections', 0)}")
    print(f"  Domain: {graph.get('domain', 'unknown')}")
    
    if task:
        # Quick keyword match check
        task_lower = task.lower()
        matched = [s for s in symbols if any(kw in s.get('name', '').lower() for kw in task_lower.split())]
        print(f"  Task: '{task}'")
        print(f"  Keyword matches: {len(matched)} symbols")
        if matched:
            print(f"  Sample matches: {[m['name'] for m in matched[:5]]}")
        print(f"  Relevance: {'HIGH' if len(matched) > 5 else 'MEDIUM' if matched else 'LOW'}")
    else:
        print(f"  Relevance: UNKNOWN (provide --task for keyword check)")
    
    print(f"\n  Next steps:")
    print(f"  argon . --precision --task \"your task\" --budget-profile micro --format compact")


def _expand_symbol_cmd(args):
    """Expand a symbol with full code and direct relationships."""
    from argon import pathspec, tiktoken, ts_pack
    try:
        engine = ArgonEngine(
            args.path,
            precision=True,
            model=args.model,
            output_dir='',
            ts_pack=ts_pack,
            tiktoken_mod=tiktoken,
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        return

    graph = engine.build_graph()
    
    # Build symbol map with file from parent node
    symbol_map = {}
    symbol_to_node = {}
    for node in graph.get('nodes', []):
        node_id = node['id']
        for sym in node.get('symbols', []):
            sid = f"{node_id}::{sym['name']}"
            sym_copy = dict(sym)
            sym_copy['file'] = node_id  # Add file from parent node
            symbol_map[sid] = sym_copy
            symbol_to_node[sid] = node_id

    sid = args.symbol
    if sid not in symbol_map:
        print(f"[!] Symbol '{sid}' not found in graph.")
        # Show similar symbols
        matches = [k for k in symbol_map if args.symbol.lower() in k.lower()][:5]
        if matches:
            print(f"  Did you mean: {matches}")
        return

    sym = symbol_map[sid]
    sym["code"] = engine._read_symbol_snippet(sym)

    # Get incoming/outgoing edges
    incoming = {}
    outgoing = {}
    for edge in graph.get('symbol_edges', []):
        src = edge['source']
        tgt = edge['target']
        edge_info = {
            "symbol": tgt,
            "kind": edge.get('kind'),
            "local": edge.get('local'),
            "line": edge.get('line'),
        }
        outgoing.setdefault(src, []).append(edge_info)
        incoming.setdefault(tgt, []).append({**edge_info, "symbol": src})

    sym["incoming"] = incoming.get(sid, [])[:20]
    sym["outgoing"] = outgoing.get(sid, [])[:20]

    # Truncate to token budget
    import tiktoken
    enc = tiktoken.encoding_for_model(args.model)
    tokens = len(enc.encode(json.dumps(sym, ensure_ascii=False)))
    if tokens > args.max_tokens:
        # Trim code if needed
        max_code_tokens = args.max_tokens - (tokens - len(enc.encode(sym.get('code', ''))))
        if max_code_tokens > 100:
            code = sym.get('code', '')
            code_tokens = len(enc.encode(code))
            if code_tokens > max_code_tokens:
                # Truncate code
                ratio = max_code_tokens / code_tokens
                keep_chars = int(len(code) * ratio)
                sym['code'] = code[:keep_chars] + "\n... (truncated)"

    print(json.dumps(sym, indent=2, ensure_ascii=False))


def main():
    # Use a custom approach: detect subcommand first, then parse accordingly
    import sys
    argv = sys.argv[1:]
    
    # Check if first arg is a known subcommand
    subcommands = {'expand-symbol', 'expand_symbol'}
    if argv and argv[0] in subcommands:
        # Parse as subcommand
        parser = argparse.ArgumentParser(description='ARGON v9.0 // UNIVERSAL_SCANNER', add_help=False)
        parser.add_argument('command', choices=['expand-symbol'])
        parser.add_argument('symbol', help='ID del símbolo (ej: file.py::function_name)')
        parser.add_argument('--max-tokens', type=int, default=2048, help='Máximo tokens en output')
        parser.add_argument('--model', default='gpt-4.1', help='Modelo para conteo de tokens')
        parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
        args = parser.parse_args(argv)
        _expand_symbol_cmd(args)
        return

    # Main command parsing
    parser = argparse.ArgumentParser(description='ARGON v9.0 // UNIVERSAL_SCANNER')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--context', action='store_true', help='Generar ARGON.md y argon_graph.json')
    parser.add_argument('--precision', action='store_true', help='Modo precision: tokens reales, .gitignore, imports resueltos, PageRank y contexto semantico')
    parser.add_argument('--task', default='', help='Tarea para seleccionar contexto precision')
    parser.add_argument('--model', default='gpt-4.1', help='Modelo para conteo real de tokens en precision')
    parser.add_argument('--format', choices=['xml', 'json', 'markdown', 'compact'], default='xml', help='Formato de salida precision')
    parser.add_argument('--view', action='store_true', help='Generar argon_view.html usando argon_template.html')
    parser.add_argument('--open-view', action='store_true', help='Abrir argon_view.html tras generarlo')
    parser.add_argument('--budget', type=int, default=4096, help='Token budget para ARGON.md (default: 4096)')
    parser.add_argument(
        '--budget-profile',
        choices=sorted(PRECISION_BUDGET_PROFILES),
        default='custom',
        help='Perfil Precision opcional: micro=1500, standard=4096, deep=8192, custom=usa --budget',
    )
    parser.add_argument('--compact', action='store_true', help='JSON compacto (sin symbols detallados)')
    parser.add_argument('--output', default=None, metavar='DIR',
                        help='Directorio de salida para ARGON.md y argon_graph.json '
                             '(default: raiz del proyecto escaneado)')
    parser.add_argument('--llm-guide', action='store_true', help='Guía rápida para LLMs: cómo usar ARGON eficientemente')
    parser.add_argument('--smart-start', action='store_true', help='Check if project has relevant code for task')

    args = parser.parse_args()

    if args.llm_guide:
        print(LLM_GUIDE)
        return

    if args.smart_start:
        _smart_start_cmd(args)
        return

    target = os.path.abspath(args.path)
    if args.output:
        output_dir = os.path.abspath(args.output)
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = target
    try:
        engine = ArgonEngine(
            target,
            precision=args.precision,
            model=args.model,
            output_dir=output_dir if args.output else '',
            ts_pack=ts_pack,
            tiktoken_mod=tiktoken,
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        return

    if args.context or args.precision:
        graph = engine.build_graph()

        if args.compact:
            for n in graph['nodes']:
                n['symbol_count'] = len(n.get('symbols', []))
                n['symbols'] = []
                if n.get('summary') and len(n['summary']) > 60:
                    n['summary'] = n['summary'][:60] + '...'

        if args.precision:
            task = args.task or "general repository understanding"
            ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md', 'compact': 'txt'}[args.format]
            engine.generate_precision_context(
                graph,
                os.path.join(output_dir, f'ARGON_PRECISION.{ext}'),
                task=task,
                max_tokens=args.budget,
                output_format=args.format,
                budget_profile=args.budget_profile,
            )
        else:
            engine.generate_context_report(graph, os.path.join(output_dir, 'ARGON.md'), max_tokens=args.budget)

        graph_path = os.path.join(output_dir, 'argon_graph.json')
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        if args.view or args.open_view:
            try:
                from argon_view import ArgonVisualizer
                template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'argon_template.html')
                view_path = os.path.join(output_dir, 'argon_view.html')
                ArgonVisualizer(graph_path, template_path).render(view_path, open_browser=args.open_view)
            except Exception as e:
                print(f"[!] No se pudo generar argon_view.html: {e}")

        s = graph['stats']
        print(f"[+] Mapeados {s['total_files']} archivos, {s['total_connections']} conexiones.")
    else:
        print("[!] Usa --context o --precision para generar el mapa del proyecto.")
        print("    Ejemplo: python argon.py . --context")
        print("    Precision: python argon.py . --precision --task \"fix auth bug\" --budget 4096 --format xml --view")
        print("    Opciones: --budget 8192 --compact")


if __name__ == '__main__':
    main()
