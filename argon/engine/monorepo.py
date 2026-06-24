"""Monorepo-aware multi-project analysis."""

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple


class MonorepoDetector:
    WORKSPACE_CONFIGS = {
        'npm': 'package.json',
        'pnpm': 'pnpm-workspace.yaml',
        'yarn': 'package.json',
        'cargo': 'Cargo.toml',
        'composer': 'composer.json',
    }

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._packages: Optional[List[Dict[str, Any]]] = None

    def detect(self) -> bool:
        return len(self.find_packages()) > 0

    def find_packages(self) -> List[Dict[str, Any]]:
        if self._packages is not None:
            return self._packages

        packages = []

        npm_workspaces = self._detect_npm_workspaces()
        if npm_workspaces:
            packages.extend(npm_workspaces)

        cargo_workspaces = self._detect_cargo_workspaces()
        if cargo_workspaces:
            packages.extend(cargo_workspaces)

        if not packages:
            for entry in os.scandir(self.root):
                if entry.is_dir() and not entry.name.startswith('.'):
                    pkg_json = os.path.join(entry.path, 'package.json')
                    if os.path.exists(pkg_json):
                        packages.append({
                            'name': entry.name,
                            'path': entry.path,
                            'type': 'npm',
                        })
                    cargo_toml = os.path.join(entry.path, 'Cargo.toml')
                    if os.path.exists(cargo_toml):
                        packages.append({
                            'name': entry.name,
                            'path': entry.path,
                            'type': 'cargo',
                        })

        self._packages = packages
        return packages

    def _detect_npm_workspaces(self) -> List[Dict[str, Any]]:
        pkg_json_path = os.path.join(self.root, 'package.json')
        if not os.path.exists(pkg_json_path):
            return []
        try:
            with open(pkg_json_path, encoding='utf-8') as f:
                config = json.load(f)
            workspaces = config.get('workspaces', [])
            if not workspaces:
                return []
            packages = []
            for ws in workspaces:
                if isinstance(ws, str):
                    if '*' in ws:
                        import glob
                        pattern = os.path.join(self.root, ws)
                        for match in glob.glob(pattern):
                            if os.path.isdir(match):
                                packages.append({
                                    'name': os.path.basename(match),
                                    'path': match,
                                    'type': 'npm',
                                    'pattern': ws,
                                })
                    else:
                        ws_path = os.path.join(self.root, ws)
                        if os.path.isdir(ws_path):
                            packages.append({
                                'name': os.path.basename(ws),
                                'path': ws_path,
                                'type': 'npm',
                                'pattern': ws,
                            })
                elif isinstance(ws, dict):
                    ws_path = os.path.join(self.root, ws.get('packages', ws.get('glob', '')))
                    if os.path.isdir(ws_path):
                        packages.append({
                            'name': os.path.basename(ws_path),
                            'path': ws_path,
                            'type': 'npm',
                        })
            return packages
        except Exception:
            return []

    def _detect_cargo_workspaces(self) -> List[Dict[str, Any]]:
        cargo_path = os.path.join(self.root, 'Cargo.toml')
        if not os.path.exists(cargo_path):
            return []
        try:
            with open(cargo_path, encoding='utf-8') as f:
                content = f.read()
            in_workspace = False
            members = []
            for line in content.splitlines():
                if '[workspace]' in line:
                    in_workspace = True
                    continue
                if in_workspace:
                    if line.strip().startswith('['):
                        break
                    if 'members' in line and '=' in line:
                        after_eq = line.split('=', 1)[1] if '=' in line else line
                        if '[' in after_eq and ']' not in after_eq:
                            continue
                        member = after_eq.strip().strip('[]",\' ')
                        if member and '*' not in member:
                            members.append(member)
                        continue
                    if line.strip().startswith('"') or line.strip().startswith("'"):
                        member = line.strip().strip('[]",\', \t')
                        if member and '*' not in member:
                            members.append(member)
            packages = []
            for member in members:
                pkg_path = os.path.join(self.root, member)
                if os.path.isdir(pkg_path):
                    packages.append({
                        'name': os.path.basename(member),
                        'path': pkg_path,
                        'type': 'cargo',
                        'member': member,
                    })
            return packages
        except Exception:
            return []


class MonorepoAnalyzer:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.detector = MonorepoDetector(root)
        self._package_graphs: Dict[str, Dict[str, Any]] = {}

    def analyze(self) -> Dict[str, Any]:
        packages = self.detector.find_packages()
        if not packages:
            return {'is_monorepo': False, 'packages': []}

        results = {
            'is_monorepo': True,
            'packages': [],
            'inter_package_edges': [],
        }

        for pkg in packages:
            pkg_result = self._analyze_package(pkg)
            results['packages'].append(pkg_result)

        results['inter_package_edges'] = self._find_inter_package_edges(packages)
        return results

    def _analyze_package(self, pkg: Dict[str, Any]) -> Dict[str, Any]:
        pkg_path = pkg['path']
        try:
            from argon.engine.graph import ArgonEngine
            engine = ArgonEngine(pkg_path, precision=True)
            graph = engine.build_graph()
            return {
                'name': pkg['name'],
                'path': pkg['path'],
                'type': pkg['type'],
                'symbols': len(graph.get('symbols', [])),
                'files': len(graph.get('nodes', [])),
                'edges': len(graph.get('edges', [])),
            }
        except Exception:
            return {
                'name': pkg['name'],
                'path': pkg['path'],
                'type': pkg['type'],
                'symbols': 0,
                'files': 0,
                'edges': 0,
            }

    def _find_inter_package_edges(self, packages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        edges = []
        pkg_paths = {pkg['path']: pkg['name'] for pkg in packages}

        for pkg in packages:
            pkg_path = pkg['path']
            for dirpath, _, filenames in os.walk(pkg_path):
                for f in filenames:
                    if f.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.rs')):
                        fpath = os.path.join(dirpath, f)
                        try:
                            with open(fpath, encoding='utf-8', errors='ignore') as fh:
                                content = fh.read(10000)
                            for other_pkg in packages:
                                if other_pkg['path'] == pkg_path:
                                    continue
                                other_name = other_pkg['name']
                                if other_name in content:
                                    edges.append({
                                        'source': pkg['name'],
                                        'target': other_name,
                                        'file': os.path.relpath(fpath, self.root),
                                    })
                        except Exception:
                            pass
        return edges
