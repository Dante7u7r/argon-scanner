import argparse
import json
import os

from argon import pathspec, tiktoken, ts_pack
from argon.engine.graph import PRECISION_BUDGET_PROFILES, ArgonEngine


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
    args = parser.parse_args()

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
