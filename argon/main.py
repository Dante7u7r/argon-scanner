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
╚════════════════════════════════════════════════════════════════════╝

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

  4. Need more? argon_expand_symbol "file.py::symbol" --max-tokens 2000

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

def main():
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
    args = parser.parse_args()

    if args.llm_guide:
        print(LLM_GUIDE)
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
