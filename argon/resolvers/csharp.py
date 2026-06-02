"""C# import resolution using .csproj and namespace conventions."""

import os
import re
from typing import Optional


class CSharpResolver:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._src_dirs = self._find_src_dirs()

    def _find_src_dirs(self) -> list:
        dirs = []
        for entry in os.scandir(self.root):
            if entry.is_dir():
                for sub in os.scandir(entry.path):
                    if sub.is_dir() and sub.name.lower() == 'bin':
                        dirs.append(entry.path)
                        break
        if not dirs:
            dirs = [self.root]
        return dirs

    def candidates(self, specifier: str, source_file: str) -> list:
        if not source_file.endswith('.cs'):
            return []
        if specifier.startswith('.'):
            return []
        parts = specifier.split('.')
        for src_dir in self._src_dirs:
            ns_path = os.path.join(src_dir, *parts)
            if os.path.isdir(ns_path):
                for name in os.listdir(ns_path):
                    if name.endswith('.cs'):
                        return [os.path.join(ns_path, name)]
            cs_file = ns_path + '.cs'
            if os.path.isfile(cs_file):
                return [cs_file]
        return []
