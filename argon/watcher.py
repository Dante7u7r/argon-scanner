import os
import sys
import json
import time
import threading
from typing import Dict, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from argon.engine.graph import ArgonEngine, PRECISION_BUDGET_PROFILES

try:
    from argon_view import ArgonVisualizer
except ImportError:
    ArgonVisualizer = None


class _ArgonWatchHandler(FileSystemEventHandler):
    def __init__(self, sentinel: "ArgonSentinel", debounce: float = 2.0):
        super().__init__()
        self.sentinel = sentinel
        self.debounce = debounce
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _is_relevant(self, path: str) -> bool:
        try:
            if os.path.isdir(path):
                return not self.sentinel.engine._should_skip(path, True)
            return not self.sentinel.engine._should_skip(path, False)
        except (OSError, PermissionError):
            return False

    def _debounce_trigger(self):
        with self._lock:
            self._timer = None
        self.sentinel.rebuild()

    def _schedule(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._debounce_trigger)
            self._timer.daemon = True
            self._timer.start()

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if not self._is_relevant(event.src_path):
            return
        self._schedule()


class ArgonSentinel:
    def __init__(
        self,
        root: str = '.',
        debounce: float = 2.0,
        precision: bool = False,
        task: str = '',
        model: str = 'gpt-4.1',
        output_format: str = 'xml',
        budget: int = 4096,
        budget_profile: str = 'custom',
    ):
        self.root = os.path.abspath(root)
        self.debounce = debounce
        self.precision = precision
        self.task = task or "general repository understanding"
        self.model = model
        self.output_format = output_format
        self.budget = budget
        self.budget_profile = budget_profile

        self.engine = ArgonEngine(
            self.root,
            precision=precision,
            model=model,
        )
        self.handler = _ArgonWatchHandler(self, debounce=debounce)

        self.graph_path = os.path.join(self.root, 'argon_graph.json')
        self.md_path = os.path.join(self.root, 'ARGON.md')
        self.html_path = os.path.join(self.root, 'argon_view.html')
        ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md'}[self.output_format]
        self.precision_path = os.path.join(self.root, f'ARGON_PRECISION.{ext}')

        base = os.path.dirname(os.path.abspath(__file__))
        self.template_path = os.path.join(base, '..', 'argon_template.html')

    def rebuild(self):
        t0 = time.time()
        print(f"[*] Cambio detectado. Reconstruyendo...")
        try:
            graph = self.engine.build_graph()
        except Exception as e:
            print(f"[!] Error en build_graph: {e}")
            return

        with open(self.graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        if self.precision:
            self.engine.generate_precision_context(
                graph,
                self.precision_path,
                task=self.task,
                max_tokens=self.budget,
                output_format=self.output_format,
                budget_profile=self.budget_profile,
            )
        else:
            self.engine.generate_context_report(graph, self.md_path, max_tokens=self.budget)

        if ArgonVisualizer and os.path.exists(self.template_path):
            viz = ArgonVisualizer(self.graph_path, self.template_path)
            viz.render(self.html_path, open_browser=False)

        elapsed = time.time() - t0
        s = graph['stats']
        cache_hits = s.get('cache_hits', 0)
        total_files = s['total_files']
        parsed_fresh = total_files - cache_hits
        print(f"    [{elapsed:.2f}s] parsed {parsed_fresh}, cached {cache_hits} — {total_files} archivos, {s['total_connections']} conexiones")

    def watch(self):
        print(f"[*] Argon Sentinel v9.1 — Vigilando: {self.root}")
        print(f"[*] Debounce: {self.debounce}s | Precision: {'ON' if self.precision else 'OFF'} | Ctrl+C para detener")
        print()

        print("[*] Escaneo inicial...")
        try:
            self.rebuild()
        except Exception as e:
            print(f"[!] Error en escaneo inicial: {e}")

        observer = Observer()
        observer.schedule(self.handler, self.root, recursive=True)
        observer.daemon = True
        observer.start()
        print(f"[*] Watchdog activo. Esperando cambios...")

        try:
            while observer.is_alive():
                observer.join(1)
        except KeyboardInterrupt:
            print("\n[!] Sentinel detenido.")
            observer.stop()
        observer.join()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='ARGON WATCH v9.0 -- Sentinel (watchdog)')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--debounce', type=float, default=2.0, help='Segundos de espera tras el ultimo cambio antes de rebuild')
    parser.add_argument('--interval', type=float, default=None, help='(deprecated) alias de --debounce')
    parser.add_argument('--precision', action='store_true', help='Usar modo precision en cada rebuild')
    parser.add_argument('--task', default='', help='Tarea para ARGON_PRECISION cuando --precision está activo')
    parser.add_argument('--model', default='gpt-4.1', help='Modelo para conteo de tokens precision')
    parser.add_argument('--format', choices=['xml', 'json', 'markdown'], default='xml', help='Formato ARGON_PRECISION')
    parser.add_argument('--budget', type=int, default=4096, help='Token budget del contexto generado')
    parser.add_argument(
        '--budget-profile',
        choices=sorted(PRECISION_BUDGET_PROFILES),
        default='custom',
        help='Perfil Precision opcional: micro=1500, standard=4096, deep=8192, custom=usa --budget',
    )
    args = parser.parse_args()

    debounce = args.debounce
    if args.interval is not None:
        debounce = args.interval

    try:
        sentinel = ArgonSentinel(
            root=args.path,
            debounce=debounce,
            precision=args.precision,
            task=args.task,
            model=args.model,
            output_format=args.format,
            budget=args.budget,
            budget_profile=args.budget_profile,
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        return
    sentinel.watch()


if __name__ == '__main__':
    main()
