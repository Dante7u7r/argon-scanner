"""CI/CD integration module for architecture quality gates."""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class CIBaseline:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.baseline_path = os.path.join(root, '.argon_baseline.json')

    def save(self, data: Dict[str, Any]) -> None:
        try:
            with open(self.baseline_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def load(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.baseline_path):
            return None
        try:
            with open(self.baseline_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def exists(self) -> bool:
        return os.path.exists(self.baseline_path)


class CIDiffer:
    def __init__(self, baseline: Dict[str, Any], current: Dict[str, Any]):
        self.baseline = baseline
        self.current = current

    def diff(self) -> Dict[str, Any]:
        baseline_files = set(self.baseline.get('files', []))
        current_files = set(self.current.get('files', []))

        new_files = current_files - baseline_files
        removed_files = baseline_files - current_files
        common_files = baseline_files & current_files

        changed_files = []
        for f in common_files:
            old_hash = self.baseline.get('file_hashes', {}).get(f)
            new_hash = self.current.get('file_hashes', {}).get(f)
            if old_hash != new_hash:
                changed_files.append(f)

        baseline_symbols = set(self.baseline.get('symbol_ids', []))
        current_symbols = set(self.current.get('symbol_ids', []))
        new_symbols = current_symbols - baseline_symbols
        removed_symbols = baseline_symbols - current_symbols

        baseline_edges = set()
        for e in self.baseline.get('edges', []):
            baseline_edges.add((e.get('source', ''), e.get('target', '')))
        current_edges = set()
        for e in self.current.get('edges', []):
            current_edges.add((e.get('source', ''), e.get('target', '')))

        new_edges = current_edges - baseline_edges
        removed_edges = baseline_edges - current_edges

        baseline_cycles = set(self.baseline.get('cycles', []))
        current_cycles = set(self.current.get('cycles', []))
        new_cycles = current_cycles - baseline_cycles

        return {
            'new_files': sorted(new_files),
            'removed_files': sorted(removed_files),
            'changed_files': sorted(changed_files),
            'new_symbols': sorted(new_symbols),
            'removed_symbols': sorted(removed_symbols),
            'new_edges': len(new_edges),
            'removed_edges': len(removed_edges),
            'new_cycles': sorted(new_cycles) if new_cycles else [],
            'summary': {
                'files_added': len(new_files),
                'files_removed': len(removed_files),
                'files_changed': len(changed_files),
                'symbols_added': len(new_symbols),
                'symbols_removed': len(removed_symbols),
                'edges_added': len(new_edges),
                'edges_removed': len(removed_edges),
                'cycles_added': len(new_cycles),
            }
        }


class CIQualityGates:
    def __init__(self, max_new_cycles: int = 0, max_files_changed_ratio: float = 0.3,
                 max_symbols_removed_ratio: float = 0.2):
        self.max_new_cycles = max_new_cycles
        self.max_files_changed_ratio = max_files_changed_ratio
        self.max_symbols_removed_ratio = max_symbols_removed_ratio

    def check(self, diff: Dict[str, Any]) -> Tuple[bool, List[str]]:
        violations = []

        if len(diff.get('new_cycles', [])) > self.max_new_cycles:
            violations.append(f"New dependency cycles detected: {len(diff['new_cycles'])}")

        total_files = len(diff.get('new_files', [])) + len(diff.get('removed_files', [])) + len(diff.get('changed_files', []))
        if total_files > 100:
            ratio = total_files / max(len(diff.get('new_files', [])) + len(diff.get('removed_files', [])) + len(diff.get('changed_files', [])), 1)
            if ratio > self.max_files_changed_ratio:
                violations.append(f"Too many files changed: {total_files}")

        baseline_symbols = len(diff.get('new_symbols', [])) + len(diff.get('removed_symbols', []))
        if baseline_symbols > 0:
            removed_ratio = len(diff.get('removed_symbols', [])) / baseline_symbols
            if removed_ratio > self.max_symbols_removed_ratio:
                violations.append(f"Too many symbols removed: {len(diff['removed_symbols'])}")

        return len(violations) == 0, violations


class CIReporter:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def generate_report(self, diff: Dict[str, Any], quality_check: Tuple[bool, List[str]]) -> str:
        passed, violations = quality_check

        lines = []
        lines.append("# ARGON CI Report")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("")
        lines.append("## Quality Gate: " + ("PASSED" if passed else "FAILED"))
        lines.append("")

        if violations:
            lines.append("### Violations")
            for v in violations:
                lines.append(f"- {v}")
            lines.append("")

        summary = diff.get('summary', {})
        lines.append("## Summary")
        lines.append(f"- Files added: {summary.get('files_added', 0)}")
        lines.append(f"- Files removed: {summary.get('files_removed', 0)}")
        lines.append(f"- Files changed: {summary.get('files_changed', 0)}")
        lines.append(f"- Symbols added: {summary.get('symbols_added', 0)}")
        lines.append(f"- Symbols removed: {summary.get('symbols_removed', 0)}")
        lines.append(f"- Edges added: {summary.get('edges_added', 0)}")
        lines.append(f"- Edges removed: {summary.get('edges_removed', 0)}")
        lines.append(f"- New cycles: {summary.get('cycles_added', 0)}")
        lines.append("")

        if diff.get('new_cycles'):
            lines.append("## New Dependency Cycles")
            for cycle in diff['new_cycles']:
                lines.append(f"- {cycle}")
            lines.append("")

        return "\n".join(lines)
