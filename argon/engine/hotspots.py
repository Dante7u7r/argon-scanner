"""Git-aware hotspot analysis — lightweight, no dependencies beyond subprocess."""

import os
import subprocess
from typing import Dict, List, Optional, Set


class GitAnalyzer:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        self._has_git: Optional[bool] = None
        self._hotspots: Optional[Dict[str, float]] = None
        self._coupling: Optional[Dict[str, Dict[str, float]]] = None

    @property
    def has_git(self) -> bool:
        if self._has_git is None:
            self._has_git = os.path.isdir(os.path.join(self.repo_root, '.git'))
        return self._has_git

    def _run(self, args: List[str]) -> str:
        try:
            result = subprocess.run(
                ['git', *args],
                capture_output=True, text=True, cwd=self.repo_root,
                timeout=15,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        return ""

    def _build_hotspots(self) -> Dict[str, float]:
        output = self._run([
            'log', '--since=4.weeks', '--name-only', '--format=',
            '--', '*.py', '*.ts', '*.tsx', '*.js', '*.jsx', '*.go',
            '*.rs', '*.java', '*.rb', '*.php', '*.cs', '*.swift',
            '*.kt', '*.scala', '*.c', '*.cpp', '*.h', '*.hpp',
        ])
        counts: Dict[str, float] = {}
        for line in output.splitlines():
            line = line.strip()
            if line:
                counts[line] = counts.get(line, 0) + 1
        if not counts:
            return {}
        max_count = max(counts.values())
        return {f: min(1.0, c / max(1, max_count)) for f, c in counts.items()}

    def _build_coupling(self, n_commits: int = 200) -> Dict[str, Dict[str, float]]:
        hashes = [
            h.strip() for h in
            self._run(['log', '--format=%H', f'-n{n_commits}']).splitlines()
            if h.strip()
        ]
        if not hashes:
            return {}

        file_changes: List[Set[str]] = []
        file_count: Dict[str, int] = {}
        for h in hashes:
            files = {
                f.strip() for f in
                self._run(['diff-tree', '--no-commit-id', '--name-only', '-r', h]).splitlines()
                if f.strip()
            }
            if len(files) >= 2:
                file_changes.append(files)
                for f in files:
                    file_count[f] = file_count.get(f, 0) + 1

        coupling: Dict[str, Dict[str, float]] = {}
        for files in file_changes:
            for a in files:
                for b in files:
                    if a >= b:
                        continue
                    coupling.setdefault(a, {})
                    coupling.setdefault(b, {})
                    coupling[a][b] = coupling[a].get(b, 0) + 1
                    coupling[b][a] = coupling[b].get(a, 0) + 1

        for f, peers in coupling.items():
            f_changes = max(1, file_count.get(f, 1))
            for peer in list(peers):
                p_changes = max(1, file_count.get(peer, 1))
                peers[peer] = min(1.0, peers[peer] / min(f_changes, p_changes))

        return coupling

    def get_hotspots(self) -> Dict[str, float]:
        if not self.has_git:
            return {}
        if self._hotspots is None:
            self._hotspots = self._build_hotspots()
        return self._hotspots

    def get_coupling(self) -> Dict[str, Dict[str, float]]:
        if not self.has_git:
            return {}
        if self._coupling is None:
            self._coupling = self._build_coupling()
        return self._coupling

    def get_score_boost(self, file_path: str, related_files: Optional[List[str]] = None) -> float:
        if not self.has_git:
            return 1.0
        hotspot = self.get_hotspots().get(file_path, 0.0)
        boost = 1.0 + (hotspot * 0.40)
        if related_files:
            coupling_map = self.get_coupling()
            peers = coupling_map.get(file_path, {})
            coupling_sum = 0.0
            for rf in related_files:
                coupling_sum += peers.get(rf, 0.0)
            if related_files:
                avg_coupling = coupling_sum / len(related_files)
                boost += avg_coupling * 0.25
        return boost
