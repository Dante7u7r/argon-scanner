#!/usr/bin/env python3
"""ARGON CI - Architecture quality gates for CI/CD pipelines."""

import argparse
import json
import os
import sys
from typing import List


def build_graph_snapshot(root: str) -> dict:
    from argon.engine.graph import ArgonEngine
    engine = ArgonEngine(root, precision=True)
    graph = engine.build_graph()

    file_hashes = {}
    for node in graph.get('nodes', []):
        fpath = os.path.join(root, node.get('id', ''))
        if os.path.exists(fpath):
            try:
                with open(fpath, 'rb') as f:
                    import hashlib
                    file_hashes[node['id']] = hashlib.md5(f.read()).hexdigest()
            except Exception:
                pass

    cycles = []
    edges = graph.get('edges', [])
    adj = {}
    for e in edges:
        src = e.get('source', '')
        dst = e.get('target', '')
        if src not in adj:
            adj[src] = []
        adj[src].append(dst)

    visited = set()
    rec_stack = set()

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycles.append(" -> ".join(path[cycle_start:] + [neighbor]))
        path.pop()
        rec_stack.remove(node)

    for node in adj:
        if node not in visited:
            dfs(node, [])

    return {
        'files': [n.get('id', '') for n in graph.get('nodes', [])],
        'symbol_ids': [s.get('id', '') for s in graph.get('symbols', [])],
        'edges': edges,
        'file_hashes': file_hashes,
        'cycles': cycles,
        'timestamp': __import__('datetime').datetime.now().isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='ARGON CI - Architecture quality gates')
    parser.add_argument('action', choices=['init', 'check', 'diff', 'report'],
                        help='CI action: init (save baseline), check (compare), diff (show changes), report (full report)')
    parser.add_argument('--root', default='.', help='Project root directory')
    parser.add_argument('--threshold-cycles', type=int, default=0, help='Max new dependency cycles allowed')
    parser.add_argument('--threshold-changed', type=float, default=0.3, help='Max file change ratio')
    parser.add_argument('--output', help='Output file for report')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    from argon.ci import CIBaseline, CIDiffer, CIQualityGates, CIReporter
    baseline_store = CIBaseline(root)

    if args.action == 'init':
        print(f"[*] Scanning project: {root}")
        snapshot = build_graph_snapshot(root)
        baseline_store.save(snapshot)
        print(f"[+] Baseline saved: {len(snapshot['files'])} files, {len(snapshot['symbol_ids'])} symbols, {len(snapshot['cycles'])} cycles")
        return 0

    if args.action in ('check', 'diff', 'report'):
        if not baseline_store.exists():
            print("[-] No baseline found. Run 'argon ci init' first.", file=sys.stderr)
            return 1

        baseline = baseline_store.load()
        print(f"[*] Scanning project: {root}")
        current = build_graph_snapshot(root)

        differ = CIDiffer(baseline, current)
        diff = differ.diff()

        gates = CIQualityGates(
            max_new_cycles=args.threshold_cycles,
            max_files_changed_ratio=args.threshold_changed,
        )
        passed, violations = gates.check(diff)

        if args.action == 'diff':
            print(json.dumps(diff, indent=2))
            return 0

        reporter = CIReporter(root)
        report = reporter.generate_report(diff, (passed, violations))

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"[+] Report saved to {args.output}")
        else:
            print(report)

        return 0 if passed else 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
