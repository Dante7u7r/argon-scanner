#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON VIEW v9.0 -- UNIVERSAL VISUALIZER
-----------------------------------------
Inyecta los datos del escaneo en la interfaz visual.
Puede abrirse en el navegador o solo generar el HTML (modo headless).
"""

import sys
import json
import os
import webbrowser
from typing import Optional, Dict


class ArgonVisualizer:
    def __init__(self, json_path: str, template_path: str):
        self.json_path = json_path
        self.template_path = template_path

    def load_data(self) -> Optional[Dict]:
        if not os.path.exists(self.json_path):
            print(f"[!] No se encuentra: {self.json_path}")
            print("[!] Ejecuta primero: python argon.py . --context")
            return None
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error al leer JSON: {e}")
            return None

    def load_template(self) -> Optional[str]:
        if not os.path.exists(self.template_path):
            print(f"[!] Template no encontrado: {self.template_path}")
            return None
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"[!] Error al leer template: {e}")
            return None

    def render(self, output_path: str = 'argon_view.html', open_browser: bool = True):
        data = self.load_data()
        if not data:
            return False

        stats = data.get('stats', {})
        if data.get('precision'):
            print(
                "[+] Precision graph: yes | "
                f"symbols={stats.get('total_symbols', len(data.get('symbols', [])))} | "
                f"symbol_calls={stats.get('total_symbol_calls', 0)}"
            )
        else:
            print("[!] Precision graph: no. SYMBOLS/CALLS modes will be disabled.")

        template = self.load_template()
        if not template:
            return False

        # Serialización segura: escapa </script> para no romper el HTML
        graph_json = json.dumps(data, ensure_ascii=False).replace('</script>', '<\\/script>')

        if '{{GRAPH_DATA}}' not in template:
            print("[!] El template no contiene el marcador {{GRAPH_DATA}}")
            return False

        rendered = template.replace('{{GRAPH_DATA}}', graph_json)

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(rendered)
        except Exception as e:
            print(f"[!] Error al escribir: {output_path}: {e}")
            return False

        print(f"[+] Visualizador generado: {output_path}")

        if open_browser:
            abs_path = os.path.abspath(output_path)
            webbrowser.open(f"file://{abs_path}")

        return True


def main():
    import argparse
    ap = argparse.ArgumentParser(description='ARGON VIEW v9.0')
    ap.add_argument('--json', default=None, help='Ruta al argon_graph.json (default: cwd o proyecto)')
    ap.add_argument('--output', default='argon_view.html', help='Archivo HTML de salida (default: argon_view.html)')
    ap.add_argument('--no-browser', action='store_true', help='No abrir el navegador automáticamente')
    args = ap.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, 'argon_template.html')

    # Busca el JSON: flag > cwd > (no encontrado)
    json_path = args.json or os.path.join(os.getcwd(), 'argon_graph.json')

    viz = ArgonVisualizer(json_path, template_path)
    viz.render(output_path=args.output, open_browser=not args.no_browser)


if __name__ == '__main__':
    main()
