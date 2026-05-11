#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON WATCH v9.0 -- MASTER SENTINEL
-------------------------------------
Vigilancia proactiva de cambios. Actualiza el grafo JSON, el ARGON.md
Y regenera el visualizador HTML en cada cambio detectado.
"""

import os
import time
import sys
import json
from typing import Dict

sys.path.append(os.path.dirname(__file__))

try:
    from argon import ArgonEngine
except ImportError:
    print("[!] Error: No se encontró argon.py.")
    sys.exit(1)

try:
    from argon_view import ArgonVisualizer
except ImportError:
    ArgonVisualizer = None
    print("[!] Aviso: argon_view.py no disponible. No se regenerará el HTML.")


class ArgonSentinel:
    def __init__(self, root: str = '.', interval: int = 2):
        self.root = os.path.abspath(root)
        self.interval = interval
        self.engine = ArgonEngine(self.root)
        self.last_state: Dict[str, float] = {}

        # Rutas de salida — siempre en la raíz del proyecto vigilado
        self.graph_path = os.path.join(self.root, 'argon_graph.json')
        self.md_path = os.path.join(self.root, 'ARGON.md')
        self.html_path = os.path.join(self.root, 'argon_view.html')

        # Template para el visualizador
        base = os.path.dirname(os.path.abspath(__file__))
        self.template_path = os.path.join(base, 'argon_template.html')

    def get_project_state(self) -> Dict[str, float]:
        state = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune skip dirs to prevent descending into node_modules/.git/etc
            dirnames[:] = [
                d for d in dirnames
                if not self.engine._should_skip(os.path.join(dirpath, d), True)
            ]
            for f in filenames:
                fpath = os.path.join(dirpath, f)
                if not self.engine._should_skip(fpath, False):
                    try:
                        state[fpath] = os.path.getmtime(fpath)
                    except (OSError, PermissionError):
                        continue
        return state

    def rebuild(self):
        """Reconstruye grafo, ARGON.md y HTML."""
        graph = self.engine.build_graph()

        # 1. JSON
        with open(self.graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        # 2. Markdown fallback
        self.engine.generate_context_report(graph, self.md_path)

        # 3. HTML visualizador
        if ArgonVisualizer and os.path.exists(self.template_path):
            viz = ArgonVisualizer(self.graph_path, self.template_path)
            viz.render(self.html_path, open_browser=False)
            print(f"[+] Visualizador actualizado: {self.html_path}")
        
        return graph['stats']

    def watch(self):
        print(f"[*] Argon Sentinel v6.0 — Vigilando: {self.root}")
        print(f"[*] Intervalo: {self.interval}s | Ctrl+C para detener")
        print()

        # Escaneo inicial
        print("[*] Escaneo inicial...")
        try:
            stats = self.rebuild()
            print(f"[+] Mapa inicial: {stats['total_files']} archivos, {stats['total_connections']} conexiones.")
        except Exception as e:
            print(f"[!] Error en escaneo inicial: {e}")

        self.last_state = self.get_project_state()

        try:
            while True:
                time.sleep(self.interval)
                current_state = self.get_project_state()

                changed = (
                    len(current_state) != len(self.last_state) or
                    any(
                        path not in self.last_state or mtime > self.last_state[path]
                        for path, mtime in current_state.items()
                    )
                )

                if changed:
                    timestamp = time.strftime('%H:%M:%S')
                    print(f"[*] Cambio detectado ({timestamp}). Actualizando...")
                    try:
                        stats = self.rebuild()
                        self.last_state = current_state
                        print(f"[+] Actualizado: {stats['total_files']} archivos, {stats['total_connections']} conexiones.")
                    except Exception as e:
                        print(f"[!] Error al actualizar: {e}")

        except KeyboardInterrupt:
            print("\n[!] Sentinel detenido.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='ARGON WATCH v6.0 -- Sentinel')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--interval', type=int, default=2, help='Intervalo de chequeo en segundos')
    args = parser.parse_args()

    sentinel = ArgonSentinel(root=args.path, interval=args.interval)
    sentinel.watch()


if __name__ == '__main__':
    main()
