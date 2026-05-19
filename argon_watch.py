#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON WATCH v9.0 -- MASTER SENTINEL
-------------------------------------
Vigilancia proactiva de cambios. Actualiza el grafo JSON, contexto clásico
o Precision, y regenera el visualizador HTML en cada cambio detectado.
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
    def __init__(
        self,
        root: str = '.',
        interval: int = 2,
        precision: bool = False,
        task: str = '',
        model: str = 'gpt-4.1',
        output_format: str = 'xml',
        budget: int = 4096,
    ):
        self.root = os.path.abspath(root)
        self.interval = interval
        self.precision = precision
        self.task = task or "general repository understanding"
        self.model = model
        self.output_format = output_format
        self.budget = budget
        self.engine = ArgonEngine(self.root, precision=precision, model=model)
        self.last_state: Dict[str, float] = {}

        # Rutas de salida — siempre en la raíz del proyecto vigilado
        self.graph_path = os.path.join(self.root, 'argon_graph.json')
        self.md_path = os.path.join(self.root, 'ARGON.md')
        self.html_path = os.path.join(self.root, 'argon_view.html')
        ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md'}[self.output_format]
        self.precision_path = os.path.join(self.root, f'ARGON_PRECISION.{ext}')

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

    def _diff_state(self, old: Dict[str, float], new: Dict[str, float]) -> Dict[str, list]:
        """Compute what changed between two project states."""
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        added = sorted(new_keys - old_keys)
        deleted = sorted(old_keys - new_keys)
        modified = sorted(
            path for path in old_keys & new_keys
            if new[path] > old[path]
        )
        return {'added': added, 'deleted': deleted, 'modified': modified}

    def rebuild(self, diff: Dict[str, list] = None):
        """Reconstruye grafo, contexto y HTML."""
        t0 = time.time()
        graph = self.engine.build_graph()
        build_time = time.time() - t0

        # 1. JSON
        with open(self.graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        # 2. Context output
        if self.precision:
            self.engine.generate_precision_context(
                graph,
                self.precision_path,
                task=self.task,
                max_tokens=self.budget,
                output_format=self.output_format,
            )
        else:
            self.engine.generate_context_report(graph, self.md_path, max_tokens=self.budget)

        # 3. HTML visualizador
        if ArgonVisualizer and os.path.exists(self.template_path):
            viz = ArgonVisualizer(self.graph_path, self.template_path)
            viz.render(self.html_path, open_browser=False)

        # 4. Report diff
        if diff:
            total_changes = len(diff['added']) + len(diff['deleted']) + len(diff['modified'])
            if total_changes <= 5:
                for path in diff['added']:
                    rel = os.path.relpath(path, self.root)
                    print(f"    + {rel}")
                for path in diff['deleted']:
                    rel = os.path.relpath(path, self.root)
                    print(f"    - {rel}")
                for path in diff['modified']:
                    rel = os.path.relpath(path, self.root)
                    print(f"    ~ {rel}")
            else:
                print(f"    {len(diff['added'])} added, {len(diff['modified'])} modified, {len(diff['deleted'])} deleted")

        cache_hits = graph['stats'].get('cache_hits', 0)
        total_files = graph['stats']['total_files']
        parsed_fresh = total_files - cache_hits
        print(f"    [{build_time:.2f}s] parsed {parsed_fresh}, cached {cache_hits}")

        return graph['stats']

    def _stats_line(self, stats: Dict[str, int]) -> str:
        base = f"{stats['total_files']} archivos, {stats['total_connections']} conexiones"
        if self.precision:
            base += (
                f", {stats.get('total_symbols', 0)} símbolos"
                f", {stats.get('total_symbol_calls', 0)} calls"
                f" ({stats.get('total_symbol_calls_local', 0)} local)"
                f", {stats.get('unresolved_imports', 0)} unresolved"
            )
        return base

    def watch(self):
        print(f"[*] Argon Sentinel v9.1 — Vigilando: {self.root}")
        print(f"[*] Intervalo: {self.interval}s | Precision: {'ON' if self.precision else 'OFF'} | Ctrl+C para detener")
        print()

        # Escaneo inicial
        print("[*] Escaneo inicial...")
        try:
            stats = self.rebuild()
            print(f"[+] Mapa inicial: {self._stats_line(stats)}.")
        except Exception as e:
            print(f"[!] Error en escaneo inicial: {e}")

        self.last_state = self.get_project_state()

        try:
            while True:
                time.sleep(self.interval)
                current_state = self.get_project_state()

                diff = self._diff_state(self.last_state, current_state)
                has_changes = any(diff.values())

                if has_changes:
                    timestamp = time.strftime('%H:%M:%S')
                    print(f"[*] Cambio detectado ({timestamp}). Actualizando...")
                    try:
                        stats = self.rebuild(diff=diff)
                        self.last_state = current_state
                        print(f"[+] Actualizado: {self._stats_line(stats)}.")
                    except Exception as e:
                        print(f"[!] Error al actualizar: {e}")

        except KeyboardInterrupt:
            print("\n[!] Sentinel detenido.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='ARGON WATCH v9.0 -- Sentinel')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--interval', type=int, default=2, help='Intervalo de chequeo en segundos')
    parser.add_argument('--precision', action='store_true', help='Usar modo precision en cada rebuild')
    parser.add_argument('--task', default='', help='Tarea para ARGON_PRECISION cuando --precision está activo')
    parser.add_argument('--model', default='gpt-4.1', help='Modelo para conteo de tokens precision')
    parser.add_argument('--format', choices=['xml', 'json', 'markdown'], default='xml', help='Formato ARGON_PRECISION')
    parser.add_argument('--budget', type=int, default=4096, help='Token budget del contexto generado')
    args = parser.parse_args()

    try:
        sentinel = ArgonSentinel(
            root=args.path,
            interval=args.interval,
            precision=args.precision,
            task=args.task,
            model=args.model,
            output_format=args.format,
            budget=args.budget,
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        return
    sentinel.watch()


if __name__ == '__main__':
    main()
