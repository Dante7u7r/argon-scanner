import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ComposerResolver:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.psr4: List[Tuple[str, str]] = []
        self._load()

    def _load(self) -> None:
        path = os.path.join(self.root, 'composer.json')
        if not os.path.exists(path):
            return
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
        except Exception:
            return
        autoload = data.get('autoload', {})
        autoload_dev = data.get('autoload-dev', {})
        for section in (autoload.get('psr-4', {}), autoload_dev.get('psr-4', {})):
            for namespace, targets in section.items():
                if isinstance(targets, str):
                    targets = [targets]
                for target in targets:
                    self.psr4.append((namespace.strip('\\'), os.path.normpath(os.path.join(self.root, target))))

    def candidates(self, specifier: str) -> List[str]:
        php_class = specifier.strip('\\')
        out: List[str] = []
        for namespace, base in sorted(self.psr4, key=lambda x: len(x[0]), reverse=True):
            if php_class == namespace:
                rel = ''
            elif php_class.startswith(namespace + '\\'):
                rel = php_class[len(namespace) + 1:]
            else:
                continue
            out.append(os.path.join(base, rel.replace('\\', os.sep)))
        return out
