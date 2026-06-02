"""Go import resolution using go.mod and standard conventions."""

import os
import re
from typing import Optional


class GoResolver:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._module_path = None
        self._load_go_mod()

    def _load_go_mod(self) -> None:
        go_mod = os.path.join(self.root, 'go.mod')
        if not os.path.exists(go_mod):
            return
        try:
            with open(go_mod, 'r', encoding='utf-8') as f:
                for line in f:
                    match = re.match(r'^module\s+(\S+)', line)
                    if match:
                        self._module_path = match.group(1)
                        break
        except OSError:
            pass

    def candidates(self, specifier: str, source_file: str) -> list:
        if not source_file.endswith('.go'):
            return []
        if specifier.startswith('.'):
            return []
        if self._module_path and specifier.startswith(self._module_path):
            rel = specifier[len(self._module_path):].lstrip('/')
            pkg_dir = os.path.join(self.root, rel)
            if os.path.isdir(pkg_dir):
                return [os.path.join(pkg_dir, 'index.go')]
            return [pkg_dir + '.go']
        if specifier.startswith('github.com/') or '/' not in specifier:
            return []
        parts = specifier.split('/')
        for i in range(len(parts), 0, -1):
            candidate = os.path.join(self.root, *parts[:i])
            if os.path.isdir(candidate):
                return [os.path.join(candidate, 'index.go')]
        return [os.path.join(self.root, *parts) + '.go']
