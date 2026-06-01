import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class TsConfigResolver:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.configs: List[Dict[str, Any]] = []
        self._load_all()

    def _read_jsonish(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            text = Path(path).read_text(encoding='utf-8')
        except OSError:
            return None
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'//.*', '', text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _merge_extends(self, path: str, seen: Optional[Set[str]] = None) -> Dict[str, Any]:
        seen = seen or set()
        data = self._read_jsonish(path) or {}
        if path in seen:
            return data
        seen.add(path)
        parent_ref = data.get('extends')
        if not parent_ref:
            return data
        parent_path = parent_ref if parent_ref.endswith('.json') else parent_ref + '.json'
        if not os.path.isabs(parent_path):
            parent_path = os.path.normpath(os.path.join(os.path.dirname(path), parent_path))
        parent = self._merge_extends(parent_path, seen) if os.path.exists(parent_path) else {}
        merged = dict(parent)
        parent_opts = dict(parent.get('compilerOptions', {}))
        parent_opts.update(data.get('compilerOptions', {}))
        merged.update(data)
        merged['compilerOptions'] = parent_opts
        return merged

    def _load_all(self) -> None:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in {'node_modules', '.git', 'dist', 'build', '.next'}]
            if 'tsconfig.json' not in filenames:
                continue
            path = os.path.join(dirpath, 'tsconfig.json')
            data = self._merge_extends(path)
            opts = data.get('compilerOptions', {})
            base = opts.get('baseUrl') or '.'
            self.configs.append({
                'dir': dirpath,
                'base_url': os.path.normpath(os.path.join(dirpath, base)),
                'paths': opts.get('paths', {}),
            })

    def candidates(self, specifier: str, source_file: str) -> List[str]:
        out: List[str] = []
        source_abs = os.path.join(self.root, source_file)
        configs = sorted(self.configs, key=lambda c: 0 if source_abs.startswith(c['dir']) else 1)
        for cfg in configs:
            for alias, targets in cfg['paths'].items():
                star = '*' in alias
                prefix, suffix = alias.split('*', 1) if star else (alias, '')
                if star:
                    if not specifier.startswith(prefix) or not specifier.endswith(suffix):
                        continue
                    end = len(specifier) - len(suffix) if suffix else None
                    middle = specifier[len(prefix):end]
                elif specifier != alias:
                    continue
                for target in targets:
                    resolved = target.replace('*', middle) if star else target
                    out.append(os.path.normpath(os.path.join(cfg['base_url'], resolved)))
            out.append(os.path.normpath(os.path.join(cfg['base_url'], specifier)))
        return out
