import fnmatch
import os
from typing import Dict, List, Optional


class IgnoreMatcher:
    def __init__(self, root: str, has_pathspec: bool = False, pathspec_mod=None):
        self.root = os.path.abspath(root)
        self.patterns: List[str] = []
        self.spec = None
        self._has_pathspec = has_pathspec
        self._pathspec = pathspec_mod
        self._load()

    def _load_file(self, rel_path: str) -> None:
        path = os.path.join(self.root, rel_path)
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.patterns.append(line)
        except OSError:
            return

    def _load(self) -> None:
        self._load_file('.gitignore')
        self._load_file('.ignore')
        self._load_file(os.path.join('.git', 'info', 'exclude'))
        if self._has_pathspec and self._pathspec and self.patterns:
            self.spec = self._pathspec.PathSpec.from_lines('gitignore', self.patterns)

    def match(self, path: str, is_dir: bool = False) -> bool:
        if not self.patterns:
            return False
        rel = os.path.relpath(path, self.root).replace('\\', '/')
        if rel == '.':
            return False
        rel_dir = rel + '/' if is_dir and not rel.endswith('/') else rel
        if self.spec:
            return self.spec.match_file(rel_dir)
        for pat in self.patterns:
            if pat.startswith('!'):
                continue
            clean = pat.strip('/')
            if fnmatch.fnmatch(rel, clean) or fnmatch.fnmatch(rel_dir, clean + '/*'):
                return True
            if '/' not in clean and any(part == clean for part in rel.split('/')):
                return True
        return False
