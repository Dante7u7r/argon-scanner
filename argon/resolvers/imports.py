import os
from typing import Dict, List, Optional, Set

from argon.models import ProjectNode
from argon.resolvers.tsconfig import TsConfigResolver
from argon.resolvers.composer import ComposerResolver
from argon.resolvers.go import GoResolver
from argon.resolvers.java import JavaResolver
from argon.resolvers.csharp import CSharpResolver


def _is_probable_external_import(specifier: str) -> bool:
    if not specifier or specifier.startswith('.') or specifier.startswith('/'):
        return False
    if specifier.startswith('@'):
        parts = specifier.split('/')
        return len(parts) <= 2
    return '/' not in specifier


class ImportResolver:
    CODE_EXTS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.php', '.json', '.rs', '.go', '.java', '.cs']

    def __init__(self, root: str, nodes: List[ProjectNode]):
        self.root = os.path.abspath(root)
        self.nodes = {n.id: n for n in nodes}
        self.path_set = set(self.nodes)
        self.tsconfig = TsConfigResolver(root)
        self.composer = ComposerResolver(root)
        self.go = GoResolver(root)
        self.java = JavaResolver(root)
        self.csharp = CSharpResolver(root)

    def _rel(self, abs_path: str) -> str:
        return os.path.relpath(abs_path, self.root).replace('\\', '/')

    def _try_file(self, abs_base: str) -> Optional[str]:
        candidates = [abs_base]
        _, ext = os.path.splitext(abs_base)
        candidates.extend(abs_base + e for e in self.CODE_EXTS)
        if not ext:
            candidates.extend(os.path.join(abs_base, 'index' + e) for e in self.CODE_EXTS)
        for cand in candidates:
            rel = self._rel(os.path.normpath(cand))
            if rel in self.path_set:
                return rel
        return None

    def _try_python_module_suffix(self, specifier: str) -> Optional[str]:
        module_path = specifier.replace('.', '/')
        candidates = [f"{module_path}.py", f"{module_path}/__init__.py"]
        matches = [
            path
            for path in self.path_set
            if path.endswith('.py') and any(path == cand or path.endswith('/' + cand) for cand in candidates)
        ]
        if not matches:
            return None
        matches.sort(key=lambda p: (p.count('/'), len(p), p))
        return matches[0]

    def _resolve_rust_use(self, source_file: str, specifier: str) -> Optional[str]:
        if not source_file.endswith('.rs'):
            return None
        source_abs = os.path.join(self.root, source_file)
        if specifier in ('crate', 'super', 'self'):
            if specifier == 'self':
                return source_file
            if specifier == 'super':
                parent_dir = os.path.dirname(source_abs)
                parent_file = os.path.join(parent_dir, 'lib.rs')
                rel = self._rel(os.path.normpath(parent_file))
                if rel in self.path_set:
                    return rel
                parent_file = os.path.join(parent_dir, 'mod.rs')
                rel = self._rel(os.path.normpath(parent_file))
                if rel in self.path_set:
                    return rel
                return None
            if specifier == 'crate':
                base_dir = os.path.dirname(source_abs)
                while base_dir and base_dir != self.root:
                    if os.path.exists(os.path.join(base_dir, 'Cargo.toml')):
                        break
                    base_dir = os.path.dirname(base_dir)
                src_dir = os.path.join(base_dir, 'src') if base_dir and base_dir != self.root else os.path.join(self.root, 'src')
                if not os.path.isdir(src_dir):
                    src_dir = self.root
                main_file = os.path.join(src_dir, 'lib.rs')
                rel = self._rel(os.path.normpath(main_file))
                if rel in self.path_set:
                    return rel
                main_file = os.path.join(src_dir, 'main.rs')
                rel = self._rel(os.path.normpath(main_file))
                if rel in self.path_set:
                    return rel
                return None
        parts = specifier.split('::')
        if parts[0] in ('crate', 'super', 'self'):
            if parts[0] == 'self':
                base_dir = os.path.dirname(source_abs)
                module_path = '::'.join(parts[1:])
            elif parts[0] == 'super':
                base_dir = os.path.dirname(os.path.dirname(source_abs))
                module_path = '::'.join(parts[1:])
            else:
                base_dir = os.path.dirname(source_abs)
                while base_dir and base_dir != self.root:
                    if os.path.exists(os.path.join(base_dir, 'Cargo.toml')):
                        break
                    base_dir = os.path.dirname(base_dir)
                src_dir = os.path.join(base_dir, 'src') if base_dir and base_dir != self.root else os.path.join(self.root, 'src')
                if not os.path.isdir(src_dir):
                    src_dir = self.root
                base_dir = src_dir
                module_path = '::'.join(parts[1:])
            if module_path:
                module_file = os.path.join(base_dir, module_path.replace('::', os.sep) + '.rs')
                rel = self._rel(os.path.normpath(module_file))
                if rel in self.path_set:
                    return rel
                mod_dir = os.path.join(base_dir, module_path.replace('::', os.sep))
                mod_file = os.path.join(mod_dir, 'mod.rs')
                rel = self._rel(os.path.normpath(mod_file))
                if rel in self.path_set:
                    return rel
                mod_file = os.path.join(mod_dir, 'lib.rs')
                rel = self._rel(os.path.normpath(mod_file))
                if rel in self.path_set:
                    return rel
                if '::' in module_path:
                    parent_path = '::'.join(module_path.split('::')[:-1])
                    parent_file = os.path.join(base_dir, parent_path.replace('::', os.sep) + '.rs')
                    rel = self._rel(os.path.normpath(parent_file))
                    if rel in self.path_set:
                        return rel
                    parent_dir = os.path.join(base_dir, parent_path.replace('::', os.sep))
                    parent_mod = os.path.join(parent_dir, 'mod.rs')
                    rel = self._rel(os.path.normpath(parent_mod))
                    if rel in self.path_set:
                        return rel
                    parent_lib = os.path.join(parent_dir, 'lib.rs')
                    rel = self._rel(os.path.normpath(parent_lib))
                    if rel in self.path_set:
                        return rel
        return None

    def resolve(self, source_file: str, specifier: str) -> Optional[str]:
        if not specifier or specifier in ('.', '..'):
            return None
        if source_file.endswith('.rs') and specifier.startswith(('crate', 'super', 'self')):
            return self._resolve_rust_use(source_file, specifier)
        if source_file.endswith('.py') and specifier.startswith('.') and not specifier.startswith(('./', '../')):
            dot_count = len(specifier) - len(specifier.lstrip('.'))
            module = specifier[dot_count:].replace('.', os.sep)
            base = os.path.join(self.root, os.path.dirname(source_file))
            for _ in range(max(0, dot_count - 1)):
                base = os.path.dirname(base)
            return self._try_file(os.path.join(base, module))
        if specifier.startswith('.'):
            base = os.path.normpath(os.path.join(self.root, os.path.dirname(source_file), specifier))
            return self._try_file(base)
        for abs_candidate in self.tsconfig.candidates(specifier, source_file):
            resolved = self._try_file(abs_candidate)
            if resolved:
                return resolved
        if source_file.endswith('.php') and '\\' in specifier:
            for abs_candidate in self.composer.candidates(specifier):
                resolved = self._try_file(abs_candidate)
                if resolved:
                    return resolved
        if source_file.endswith('.go'):
            for abs_candidate in self.go.candidates(specifier, source_file):
                resolved = self._try_file(abs_candidate)
                if resolved:
                    return resolved
        if source_file.endswith('.java'):
            for abs_candidate in self.java.candidates(specifier, source_file):
                resolved = self._try_file(abs_candidate)
                if resolved:
                    return resolved
        if source_file.endswith('.cs'):
            for abs_candidate in self.csharp.candidates(specifier, source_file):
                resolved = self._try_file(abs_candidate)
                if resolved:
                    return resolved
        if source_file.endswith('.py') and '.' in specifier:
            resolved = self._try_file(os.path.join(self.root, specifier.replace('.', os.sep)))
            if resolved:
                return resolved
            resolved = self._try_python_module_suffix(specifier)
            if resolved:
                return resolved
        return self._try_file(os.path.join(self.root, specifier))
