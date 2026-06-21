import os
import sys
import json
import time
import threading
from typing import Dict, List, Optional, Set

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
        self._changed: Set[str] = set()

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
        changed = list(self._changed)
        self._changed.clear()
        self.sentinel.rebuild(changed_files=changed)

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
        rel = os.path.relpath(event.src_path, self.sentinel.root)
        with self._lock:
            self._changed.add(rel)
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
        self._prev_graph: Optional[dict] = None

        self.graph_path = os.path.join(self.root, 'argon_graph.json')
        self.md_path = os.path.join(self.root, 'ARGON.md')
        self.html_path = os.path.join(self.root, 'argon_view.html')
        self.delta_path = os.path.join(self.root, 'ARGON_DELTA.md')
        ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md', 'compact': 'txt'}[self.output_format]
        self.precision_path = os.path.join(self.root, f'ARGON_PRECISION.{ext}')

        base = os.path.dirname(os.path.abspath(__file__))
        self.template_path = os.path.join(base, '..', 'argon_template.html')

    def rebuild(self, changed_files: Optional[List[str]] = None):
        t0 = time.time()
        if changed_files:
            print(f"[*] Cambio detectado ({len(changed_files)} archivos). Reconstruyendo incremental...")
        else:
            print(f"[*] Escaneo inicial. Reconstruyendo...")
        try:
            graph = self.engine.build_graph(changed_files=changed_files)
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

        if self._prev_graph and changed_files:
            delta = self._compute_delta(self._prev_graph, graph, changed_files)
            if delta['added'] or delta['removed'] or delta['changed']:
                print(f"    Δ: +{delta['added']} añadidos  -{delta['removed']} eliminados  ~{delta['changed']} modificados  →{delta['affected']} afectados")
                # Si los cambios son pocos, los listamos en consola
                total_changes = delta['added'] + delta['removed'] + delta['changed']
                if total_changes <= 5:
                    for f in delta.get('added_files', []):
                        print(f"      + {f}")
                    for f in delta.get('removed_files', []):
                        print(f"      - {f}")
                    for f in delta.get('changed_files', []):
                        print(f"      ~ {f}")
                self._write_delta(delta)
        self._prev_graph = graph

    def _compute_delta(self, prev: dict, curr: dict, changed_files: List[str]) -> dict:
        prev_nodes = {n['id'] for n in prev.get('nodes', [])}
        curr_nodes = {n['id'] for n in curr.get('nodes', [])}
        added = sorted(curr_nodes - prev_nodes)
        removed = sorted(prev_nodes - curr_nodes)
        changed = [f for f in changed_files if f in curr_nodes and f in prev_nodes]

        edge_targets: Dict[str, List[str]] = {}
        for edge in curr.get('edges', []):
            src = edge.get('source', '')
            tgt = edge.get('target', '')
            if src and tgt:
                edge_targets.setdefault(tgt, []).append(src)

        affected: set = set()
        for f in changed + added:
            affected.update(edge_targets.get(f, []))
        affected -= set(changed) | set(added)

        return {
            'added': len(added), 'added_files': added[:20],
            'removed': len(removed), 'removed_files': removed[:20],
            'changed': len(changed), 'changed_files': changed[:20],
            'affected': len(affected), 'affected_files': sorted(affected)[:20],
            'total_files': len(curr_nodes),
        }

    def _write_delta(self, delta: dict) -> None:
        lines = [
            f"# ARGON DELTA REPORT",
            f"Files: {delta['total_files']} | +{delta['added']}/-{delta['removed']}/~{delta['changed']}",
            f"Affected dependents: {delta['affected']}",
            "",
        ]
        if delta['added_files']:
            lines.append("## Added files")
            for f in delta['added_files']:
                lines.append(f"- {f}")
            lines.append("")
        if delta['removed_files']:
            lines.append("## Removed files")
            for f in delta['removed_files']:
                lines.append(f"- {f}")
            lines.append("")
        if delta['changed_files']:
            lines.append("## Changed files")
            for f in delta['changed_files']:
                lines.append(f"- {f}")
            lines.append("")
        if delta['affected_files']:
            lines.append("## Affected dependents (import changed files)")
            for f in delta['affected_files']:
                lines.append(f"- {f}")
            lines.append("")
        with open(self.delta_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

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
