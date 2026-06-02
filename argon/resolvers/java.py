"""Java import resolution using Maven/Gradle conventions."""

import os
from typing import Optional


class JavaResolver:
    SRC_DIRS = ['src/main/java', 'src/test/java', 'src']

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def candidates(self, specifier: str, source_file: str) -> list:
        if not source_file.endswith('.java'):
            return []
        if specifier.startswith('.'):
            return []
        parts = specifier.split('.')
        for src_dir in self.SRC_DIRS:
            base = os.path.join(self.root, src_dir)
            if not os.path.isdir(base):
                continue
            pkg_path = os.path.join(base, *parts)
            if os.path.isdir(pkg_path):
                for name in os.listdir(pkg_path):
                    if name.endswith('.java'):
                        return [os.path.join(pkg_path, name)]
            java_file = pkg_path + '.java'
            if os.path.isfile(java_file):
                return [java_file]
        return []
