#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON v9.0 // UNIVERSAL ARCHITECTURE SCANNER
--------------------------------------------
Dual parser: Tree-sitter (AST) con fallback a regex mejorado.
Token budget system para consumo óptimo por IAs.
O(N) edge builder optimizado para proyectos enormes.
"""

import os
import json
import re
import argparse
import datetime
import fnmatch
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from xml.sax.saxutils import escape as xml_escape

# ---------------------------------------------------------------------------
# JIT Auto-Bootstrap: auto-install missing dependencies
# ---------------------------------------------------------------------------
from argon_deps import ensure as _ensure_dep

# Tree-sitter
_HAS_TREESITTER = False
_HAS_TREESITTER_PROCESS = False
ts_pack = None
try:
    import tree_sitter_language_pack as ts_pack
    from tree_sitter_language_pack import get_language, get_parser as ts_get_parser
    _HAS_TREESITTER = True
    _HAS_TREESITTER_PROCESS = hasattr(ts_pack, 'process') and hasattr(ts_pack, 'ProcessConfig')
except ImportError:
    # Attempt auto-install
    _ts_core = _ensure_dep("tree-sitter", "tree_sitter", description="AST parser core")
    _ts_pack = _ensure_dep("tree-sitter-language-pack", "tree_sitter_language_pack", description="AST language grammars")
    if _ts_pack is not None:
        ts_pack = _ts_pack
        from tree_sitter_language_pack import get_language, get_parser as ts_get_parser
        _HAS_TREESITTER = True
        _HAS_TREESITTER_PROCESS = hasattr(ts_pack, 'process') and hasattr(ts_pack, 'ProcessConfig')
    else:
        # Legacy fallback
        try:
            from tree_sitter_languages import get_language, get_parser as ts_get_parser
            _HAS_TREESITTER = True
        except ImportError:
            pass

# tiktoken
_HAS_TIKTOKEN = False
tiktoken = _ensure_dep("tiktoken", "tiktoken", description="real token counting")
if tiktoken is not None:
    _HAS_TIKTOKEN = True

# pathspec
_HAS_PATHSPEC = False
pathspec = _ensure_dep("pathspec", "pathspec", description="gitignore parser")
if pathspec is not None:
    _HAS_PATHSPEC = True

# =========================================================================
# DATA MODELS
# =========================================================================

@dataclass
class Symbol:
    name: str
    kind: str
    line: int
    end_line: int = 0
    summary: str = ""
    signature: str = ""
    exported: bool = False

@dataclass
class ProjectNode:
    id: str
    type: str
    lines: int = 0
    size_bytes: int = 0
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    import_records: List[Dict[str, Any]] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    unresolved_imports: List[str] = field(default_factory=list)
    resolved_imports: Dict[str, str] = field(default_factory=dict)
    summary: str = ""
    importance: float = 0.0
    pagerank: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# =========================================================================
# TOKEN ESTIMATION
# =========================================================================

def estimate_tokens(text: str) -> int:
    """~4 chars per token heuristic."""
    return max(1, len(text) // 4)


class TokenCounter:
    def __init__(self, model: str = "gpt-4.1", strict: bool = False):
        self.model = model
        self.encoder = None
        if _HAS_TIKTOKEN:
            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except Exception:
                try:
                    self.encoder = tiktoken.get_encoding("o200k_base")
                except Exception:
                    self.encoder = None
        if strict and self.encoder is None:
            raise RuntimeError(
                "Precision mode requires tiktoken for real token budgets. "
                "Install it with: pip install tiktoken"
            )

    def count(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        return estimate_tokens(text)

# =========================================================================
# STDLIB / PACKAGE FILTER
# =========================================================================

STDLIB_NOISE = {
    'os', 're', 'sys', 'json', 'time', 'math', 'random', 'datetime',
    'pathlib', 'typing', 'dataclasses', 'collections', 'itertools',
    'functools', 'io', 'abc', 'enum', 'copy', 'hashlib', 'base64',
    'urllib', 'http', 'threading', 'subprocess', 'shutil', 'glob',
    'argparse', 'logging', 'unittest', 'string', 'struct', 'socket',
    'contextlib', 'traceback', 'inspect', 'ast', 'textwrap', 'uuid',
    'asyncio', 'multiprocessing', 'signal', 'tempfile', 'pickle',
    'csv', 'xml', 'html', 'email', 'sqlite3', 'decimal',
    'fs', 'path', 'crypto', 'events', 'stream', 'util', 'url',
    'https', 'net', 'dns', 'child_process', 'process', 'buffer',
    'assert', 'cluster', 'readline', 'zlib', 'tls',
    'react', 'vue', 'angular', 'svelte', 'express', 'fastapi',
    'flask', 'django', 'fastify', 'axios', 'lodash', 'moment',
    'numpy', 'pandas', 'matplotlib', 'scipy', 'sklearn', 'torch',
    'requests', 'pytest', 'click', 'pydantic', 'sqlalchemy',
    'next', 'nuxt', 'vite', 'webpack', 'babel', 'eslint',
    'tailwindcss', 'prisma', 'mongoose', 'sequelize', 'typeorm',
    'java', 'javax', 'android',
    'fmt', 'strings', 'strconv', 'errors', 'context', 'sync',
    'testing', 'encoding', 'reflect', 'runtime', 'sort', 'bytes',
    'std', 'core', 'alloc', 'tokio', 'serde', 'anyhow', 'clap',
}

SYMBOL_NOISE = {
    'ValueError', 'TypeError', 'RuntimeError', 'Exception', 'Error',
    'Promise', 'Map', 'Set', 'Array', 'Object', 'String', 'Number',
}

PRECISION_BUDGET_PROFILES = {
    'custom': {'tokens': None, 'full_code_ratio': 0.72, 'expansion_items': 8},
    'micro': {'tokens': 1500, 'full_code_ratio': 0.62, 'expansion_items': 3},
    'standard': {'tokens': 4096, 'full_code_ratio': 0.72, 'expansion_items': 8},
    'deep': {'tokens': 8192, 'full_code_ratio': 0.80, 'expansion_items': 12},
}


def resolve_precision_budget(max_tokens: int, budget_profile: str = 'custom') -> Tuple[int, Dict[str, Any]]:
    profile_name = (budget_profile or 'custom').lower().strip()
    if profile_name not in PRECISION_BUDGET_PROFILES:
        raise ValueError(
            "budget_profile must be one of: "
            + ", ".join(sorted(PRECISION_BUDGET_PROFILES))
        )
    profile = dict(PRECISION_BUDGET_PROFILES[profile_name])
    tokens = profile.get('tokens')
    resolved = int(tokens if tokens is not None else max_tokens)
    profile['name'] = profile_name
    profile['tokens'] = resolved
    return resolved, profile

# =========================================================================
# TREE-SITTER PARSER (primary if available)
# =========================================================================

TS_LANG_MAP = {
    'py': 'python', 'js': 'javascript', 'jsx': 'javascript',
    'ts': 'typescript', 'tsx': 'tsx',
    'java': 'java', 'cs': 'c_sharp', 'go': 'go',
    'rs': 'rust', 'cpp': 'cpp', 'c': 'c', 'h': 'c', 'hpp': 'cpp',
    'rb': 'ruby', 'php': 'php', 'swift': 'swift', 'kt': 'kotlin',
    'scala': 'scala', 'lua': 'lua', 'r': 'r',
    'ex': 'elixir', 'exs': 'elixir',
    'sh': 'bash', 'html': 'html', 'css': 'css',
    'sql': 'sql', 'toml': 'toml', 'yaml': 'yaml', 'yml': 'yaml',
    'json': 'json', 'md': 'markdown',
}

TS_SYMBOL_NODES = {
    'python': {'function_definition': 'func', 'class_definition': 'class'},
    'javascript': {'function_declaration': 'func', 'class_declaration': 'class', 'method_definition': 'func'},
    'typescript': {'function_declaration': 'func', 'class_declaration': 'class', 'method_definition': 'func', 'interface_declaration': 'interface'},
    'tsx': {'function_declaration': 'func', 'class_declaration': 'class', 'method_definition': 'func', 'interface_declaration': 'interface'},
    'java': {'method_declaration': 'func', 'class_declaration': 'class', 'interface_declaration': 'interface', 'enum_declaration': 'enum', 'constructor_declaration': 'func'},
    'c_sharp': {'method_declaration': 'func', 'class_declaration': 'class', 'interface_declaration': 'interface', 'enum_declaration': 'enum', 'struct_declaration': 'struct'},
    'go': {'function_declaration': 'func', 'method_declaration': 'func', 'type_declaration': 'type'},
    'rust': {'function_item': 'func', 'struct_item': 'struct', 'enum_item': 'enum', 'trait_item': 'trait', 'impl_item': 'impl'},
    'cpp': {'function_definition': 'func', 'class_specifier': 'class', 'struct_specifier': 'struct'},
    'c': {'function_definition': 'func', 'struct_specifier': 'struct', 'enum_specifier': 'enum'},
    'ruby': {'method': 'func', 'class': 'class', 'module': 'module'},
    'php': {'function_definition': 'func', 'class_declaration': 'class', 'method_declaration': 'func'},
    'kotlin': {'function_declaration': 'func', 'class_declaration': 'class', 'object_declaration': 'class'},
    'swift': {'function_declaration': 'func', 'class_declaration': 'class', 'struct_declaration': 'struct', 'protocol_declaration': 'interface'},
}

TS_DEFAULT_SYMBOLS = {
    'function_definition': 'func', 'function_declaration': 'func',
    'method_definition': 'func', 'method_declaration': 'func',
    'class_definition': 'class', 'class_declaration': 'class',
    'struct_declaration': 'struct', 'interface_declaration': 'interface',
    'enum_declaration': 'enum',
}


class TreeSitterExtractor:
    def __init__(self):
        self._parsers = {}

    def _get_parser(self, lang: str):
        if lang not in self._parsers:
            try:
                self._parsers[lang] = ts_get_parser(lang)
            except Exception:
                self._parsers[lang] = None
        return self._parsers[lang]

    def _find_name(self, node) -> Optional[str]:
        for child in node.children:
            if child.type in ('identifier', 'name', 'type_identifier', 'property_identifier'):
                return child.text.decode('utf-8', errors='replace')
        for child in node.children:
            if 'declarator' in child.type:
                return self._find_name(child)
        return None

    def _signature(self, content: str, start_line: int) -> str:
        lines = content.splitlines()
        if not lines or start_line < 1 or start_line > len(lines):
            return ""
        sig = lines[start_line - 1].strip()
        if len(sig) > 180:
            sig = sig[:177] + "..."
        return sig

    def _is_exported(self, content: str, start_line: int) -> bool:
        lines = content.splitlines()
        if not lines or start_line < 1 or start_line > len(lines):
            return False
        current = lines[start_line - 1].strip()
        prev = lines[start_line - 2].strip() if start_line > 1 else ""
        return current.startswith("export ") or prev.startswith("export ")

    def _kind_from_pack(self, kind: Any) -> str:
        text = str(kind).lower()
        if 'class' in text:
            return 'class'
        if 'interface' in text:
            return 'interface'
        if 'method' in text or 'function' in text:
            return 'func'
        if 'enum' in text:
            return 'enum'
        if 'struct' in text:
            return 'struct'
        return 'symbol'

    def _extract_with_process(self, content: str, lang: str) -> List[Symbol]:
        if not _HAS_TREESITTER_PROCESS or ts_pack is None:
            return []
        try:
            result = ts_pack.process(
                content,
                ts_pack.ProcessConfig(language=lang, structure=True, imports=False, exports=True, symbols=True),
            )
        except Exception:
            return []

        lines = content.splitlines()
        export_lines = set()
        for item in getattr(result, 'exports', []) or []:
            span = getattr(item, 'span', None)
            if span is not None:
                export_lines.add(getattr(span, 'start_line', -10) + 1)

        symbols: List[Symbol] = []
        seen: Set[Tuple[str, int]] = set()

        def add_item(item: Any) -> None:
            name = getattr(item, 'name', None)
            span = getattr(item, 'span', None)
            if not name or span is None:
                return
            if name.startswith('export '):
                return
            start_line = getattr(span, 'start_line', 0) + 1
            end_line = getattr(span, 'end_line', getattr(span, 'start_line', 0)) + 1
            key = (name, start_line)
            if key in seen:
                return
            seen.add(key)
            signature = getattr(item, 'signature', None) or self._signature(content, start_line)
            exported = self._is_exported(content, start_line) or start_line in export_lines
            symbols.append(Symbol(
                name=name,
                kind=self._kind_from_pack(getattr(item, 'kind', None)),
                line=start_line,
                end_line=end_line,
                signature=signature or "",
                exported=exported,
            ))

        def walk_structure(items: List[Any]) -> None:
            for item in items:
                add_item(item)
                walk_structure(getattr(item, 'children', []) or [])

        walk_structure(getattr(result, 'structure', []) or [])
        for item in getattr(result, 'symbols', []) or []:
            add_item(item)
        return symbols

    def extract(self, content: str, ext: str) -> List[Symbol]:
        lang = TS_LANG_MAP.get(ext)
        if not lang:
            return []
        parser = self._get_parser(lang)
        if not parser or not hasattr(parser, 'parse'):
            return self._extract_with_process(content, lang)
        try:
            tree = parser.parse(content.encode('utf-8', errors='replace'))
        except Exception:
            return []

        symbol_map = TS_SYMBOL_NODES.get(lang, TS_DEFAULT_SYMBOLS)
        symbols = []
        seen = set()

        def walk(node):
            if node.type in symbol_map:
                name = self._find_name(node)
                if name and name not in seen and len(name) > 1:
                    start_line = node.start_point[0] + 1
                    symbols.append(Symbol(
                        name=name,
                        kind=symbol_map[node.type],
                        line=start_line,
                        end_line=node.end_point[0] + 1,
                        signature=self._signature(content, start_line),
                        exported=self._is_exported(content, start_line),
                    ))
                    seen.add(name)
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return symbols

# =========================================================================
# REGEX PARSER (fallback — improved for Java/C#/JS)
# =========================================================================

# Keywords that are NOT function names (false positive filter)
_KW_BLACKLIST = frozenset({
    'if', 'else', 'for', 'while', 'switch', 'case', 'return', 'throw',
    'catch', 'try', 'new', 'delete', 'typeof', 'instanceof', 'void',
    'null', 'true', 'false', 'this', 'super', 'import', 'export',
    'from', 'class', 'extends', 'implements', 'interface', 'package',
    'using', 'namespace', 'var', 'let', 'const', 'int', 'string',
    'bool', 'float', 'double', 'long', 'short', 'byte', 'char',
    'boolean', 'object', 'dynamic', 'readonly', 'where', 'select',
})

_RE_KEYWORD_FUNC = re.compile(
    r'\b(?:def|fn|func|function|procedure|sub|method)\s+([\w]+)\s*[(<]'
)
_RE_TYPED_FUNC = re.compile(
    r'^\s*'
    r'(?:(?:public|private|protected|internal|static|abstract|virtual|override|'
    r'sealed|final|async|synchronized|native|volatile)\s+)*'
    r'(?:[\w<>\[\],?\s]+\s+)'
    r'([\w]+)\s*\('
)
_RE_ARROW_FUNC = re.compile(
    r'^\s*(?:export\s+)?(?:const|let|var)\s+([\w]+)\s*=\s*(?:async\s*)?(?:\(|function\s*\()'
)
_RE_CLASS = re.compile(
    r'\b(?:class|struct|interface|trait|enum|contract|namespace|module)\s+([\w]+)'
)
_RE_IMPORT = re.compile(
    r'^\s*(?:import|from|require|include|use|using)\s+[\'"]?([\w./\-@]+)'
)
# TS/JS: } from "./path" or from "./path"
_RE_FROM_IMPORT = re.compile(
    r'\bfrom\s+["\']([\w./@\-]+)["\']'
)
# TS/JS: require("./path")
_RE_REQUIRE = re.compile(
    r'\brequire\s*\(\s*["\']([\w./@\-]+)["\']\s*\)'
)
_RE_IMPORT_NAMED = re.compile(
    r'^\s*import\s+(?:type\s+)?(?:(?P<default>[\w$]+)\s*,\s*)?(?:\{(?P<named>[^}]+)\}|\*\s+as\s+(?P<namespace>[\w$]+))?\s*from\s+["\'](?P<source>[^"\']+)["\']'
)
_RE_IMPORT_SIDE_EFFECT = re.compile(r'^\s*import\s+["\'](?P<source>[^"\']+)["\']')
_RE_EXPORT_FROM = re.compile(r'^\s*export\s+(?P<body>\*|\{[^}]+\})\s+from\s+["\'](?P<source>[^"\']+)["\']')
_RE_EXPORT_DECL = re.compile(
    r'^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const|let|var)\s+(?P<name>[\w$]+)'
)
_RE_EXPORT_DEFAULT_ANON = re.compile(
    r'^\s*export\s+default\s+(?:async\s+)?(?:function|class)?\s*(?P<name>[\w$]+)?'
)
_RE_PY_FROM_IMPORT = re.compile(r'^\s*from\s+(?P<source>[\w.]+)\s+import\s+(?P<named>[\w,\s]+)')
_RE_PHP_USE = re.compile(r'^\s*use\s+(?P<name>[A-Za-z_][\w\\]*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\s*;')
_RE_PHP_NAMESPACE = re.compile(r'^\s*namespace\s+(?P<name>[A-Za-z_][\w\\]*)\s*;')
_COMMENT_PATS = [
    re.compile(r'^\s*#\s*(.+)'),
    re.compile(r'^\s*//\s*(.+)'),
    re.compile(r'^\s*\*\s*(.+)'),
    re.compile(r'^\s*--\s*(.+)'),
    re.compile(r'^\s*;\s*(.+)'),
]

IMPORT_EXTS = {
    'py', 'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs',
    'java', 'go', 'rs', 'php', 'rb', 'cs', 'c', 'cpp', 'h', 'hpp',
    'swift', 'kt', 'scala', 'ex', 'exs', 'lua', 'r', 'jl',
    'sh', 'bat', 'ps1',
}
_DOCSTRING_PATS = [
    re.compile(r'^\s*"""(.+?)"""'),
    re.compile(r"^\s*'''(.+?)'''"),
    re.compile(r'^\s*/\*\*?\s*(.+)'),
]


def _regex_extract(lines: List[str]) -> Tuple[List[Symbol], List[str]]:
    symbols = []
    imports = []
    seen: Set[str] = set()
    in_template = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        skip_import_scan = in_template
        if _has_unescaped_backtick(line):
            in_template = not in_template
        # Classes
        m = _RE_CLASS.search(line)
        if m:
            name = m.group(1)
            if name not in seen:
                symbols.append(Symbol(name=name, kind='class', line=i))
                seen.add(name)

        # Functions: try keyword, typed, arrow
        name = None
        for pat in (_RE_KEYWORD_FUNC, _RE_TYPED_FUNC, _RE_ARROW_FUNC):
            if pat is _RE_TYPED_FUNC and re.match(r'^(return|throw|if|for|while|switch|case|await|yield)\b', stripped):
                continue
            m = pat.search(line)
            if m:
                name = m.group(1)
                break
        if name and name not in seen and len(name) > 1 and name.lower() not in _KW_BLACKLIST:
            symbols.append(Symbol(name=name, kind='func', line=i))
            seen.add(name)

        if not skip_import_scan:
            # Imports: try multiple patterns
            for pat in (_RE_IMPORT, _RE_FROM_IMPORT, _RE_REQUIRE):
                for m in pat.finditer(line):
                    imp = m.group(1).strip().strip('"\'')
                    # Skip relative dot-only imports like "."
                    if imp in ('.', '..'):
                        continue
                    root = imp.split('.')[0].split('/')[0].lstrip('@').split('/')[0]
                    if root.lower() not in STDLIB_NOISE and imp not in imports:
                        imports.append(imp)

    return symbols, imports


def _has_unescaped_backtick(line: str) -> bool:
    count = 0
    escaped = False
    for ch in line:
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if ch == '`':
            count += 1
    return count % 2 == 1


def _split_named_imports(named: str) -> List[str]:
    out = []
    for part in named.split(','):
        item = part.strip()
        if not item:
            continue
        if ' as ' in item:
            item = item.split(' as ', 1)[0].strip()
        out.append(item)
    return out


def _split_named_specifiers(named: str) -> List[Dict[str, str]]:
    out = []
    for part in named.split(','):
        item = part.strip()
        if not item:
            continue
        if ' as ' in item:
            imported, local = [p.strip() for p in item.split(' as ', 1)]
        else:
            imported = local = item
        out.append({'imported': imported, 'local': local})
    return out


def _extract_import_records(lines: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    exports: List[str] = []
    in_template = False
    for i, line in enumerate(lines, 1):
        skip_import_scan = in_template
        if _has_unescaped_backtick(line):
            in_template = not in_template
        if skip_import_scan:
            continue
        m = _RE_IMPORT_NAMED.match(line)
        if m:
            names = []
            specifiers = []
            if m.group('default'):
                names.append('default')
                specifiers.append({'imported': 'default', 'local': m.group('default')})
            if m.group('named'):
                names.extend(_split_named_imports(m.group('named')))
                specifiers.extend(_split_named_specifiers(m.group('named')))
            if m.group('namespace'):
                names.append('*')
                specifiers.append({'imported': '*', 'local': m.group('namespace')})
            records.append({
                'source': m.group('source'),
                'line': i,
                'names': names,
                'specifiers': specifiers,
                'kind': 'import',
            })
            continue
        m = _RE_IMPORT_SIDE_EFFECT.match(line)
        if m:
            records.append({'source': m.group('source'), 'line': i, 'names': [], 'kind': 'import'})
            continue
        m = _RE_REQUIRE.search(line)
        if m:
            records.append({'source': m.group(1), 'line': i, 'names': [], 'kind': 'require'})
            continue
        m = _RE_PY_FROM_IMPORT.match(line)
        if m:
            names = [name.strip() for name in m.group('named').split(',') if name.strip()]
            records.append({
                'source': m.group('source'),
                'line': i,
                'names': names,
                'specifiers': [{'imported': name, 'local': name} for name in names],
                'kind': 'import',
            })
            continue
        m = _RE_EXPORT_FROM.match(line)
        if m:
            names = ['*'] if m.group('body') == '*' else _split_named_imports(m.group('body').strip('{}'))
            specifiers = [{'imported': '*', 'local': '*'}] if names == ['*'] else _split_named_specifiers(m.group('body').strip('{}'))
            records.append({'source': m.group('source'), 'line': i, 'names': names, 'specifiers': specifiers, 'kind': 're-export'})
            exports.extend(names)
            continue
        m = _RE_EXPORT_DECL.match(line)
        if m:
            exports.append(m.group('name'))
            if line.strip().startswith('export default'):
                exports.append('default')
            continue
        m = _RE_EXPORT_DEFAULT_ANON.match(line)
        if m:
            exports.append('default')
            if m.group('name'):
                exports.append(m.group('name'))
        m = _RE_PHP_USE.match(line)
        if m:
            name = m.group('name')
            local = m.group('alias') or name.rsplit('\\', 1)[-1]
            records.append({
                'source': name,
                'line': i,
                'names': [local],
                'specifiers': [{'imported': local, 'local': local}],
                'kind': 'php-use',
            })
    return records, list(dict.fromkeys(exports))


def _extract_cortex(lines: List[str]) -> str:
    NOISE = {'coding', 'utf-8', 'utf8', '!/usr', '!/bin', 'copyright', 'license', 'all rights'}
    cortex = []
    for line in lines[:30]:
        text = None
        for pat in _DOCSTRING_PATS:
            m = pat.match(line)
            if m:
                text = m.group(1).strip()
                break
        if text is None:
            for pat in _COMMENT_PATS:
                m = pat.match(line)
                if m:
                    text = m.group(1).strip()
                    break
        if text and len(text) > 8:
            if any(n in text.lower() for n in NOISE):
                continue
            if re.match(r'^[-=*#_/\\|:. ]+$', text):
                continue
            cortex.append(text)
            if len(cortex) >= 3:
                break
    return " // ".join(cortex) if cortex else ""


def _infer_symbol_end_line(lines: List[str], start_line: int) -> int:
    if not lines or start_line < 1 or start_line > len(lines):
        return start_line
    start_idx = start_line - 1
    first = lines[start_idx]
    base_indent = len(first) - len(first.lstrip())
    if first.rstrip().endswith(':'):
        end_line = start_line
        saw_child = False
        for idx in range(start_idx + 1, len(lines)):
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith('#'):
                if saw_child:
                    end_line = idx + 1
                continue
            indent = len(lines[idx]) - len(lines[idx].lstrip())
            if indent <= base_indent:
                break
            saw_child = True
            end_line = idx + 1
        return end_line
    if '{' in first or any('{' in line for line in lines[start_idx:min(len(lines), start_idx + 3)]):
        depth = 0
        seen_open = False
        for idx in range(start_idx, len(lines)):
            line = re.sub(r'["\'].*?["\']', '""', lines[idx])
            depth += line.count('{')
            if line.count('{'):
                seen_open = True
            depth -= line.count('}')
            if seen_open and depth <= 0:
                return idx + 1
    for idx in range(start_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        indent = len(lines[idx]) - len(lines[idx].lstrip())
        if indent <= base_indent:
            return idx
    return start_line

# =========================================================================
# UNIVERSAL PARSER
# =========================================================================

class UniversalParser:
    def __init__(self, root: str):
        self.root = root
        self._ts = TreeSitterExtractor() if _HAS_TREESITTER else None
        self.mode = 'tree-sitter' if _HAS_TREESITTER else 'regex'

    def safe_read(self, filepath: str) -> str:
        for enc in ['utf-8', 'utf-16', 'latin-1', 'cp1252']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    return f.read()
            except Exception:
                continue
        return ""

    def parse(self, filepath: str) -> ProjectNode:
        rel = os.path.relpath(filepath, self.root).replace('\\', '/')
        ext_raw = os.path.splitext(filepath)[1].lower() or 'no-ext'
        ext = ext_raw[1:] if ext_raw.startswith('.') else ext_raw
        node = ProjectNode(id=rel, type=ext, size_bytes=os.path.getsize(filepath))

        content = self.safe_read(filepath)
        if not content:
            return node

        lines = content.splitlines()
        node.lines = len(lines)

        # Try Tree-sitter
        if self._ts and ext in TS_LANG_MAP:
            ts_syms = self._ts.extract(content, ext)
            if ts_syms:
                regex_syms, imports = _regex_extract(lines)
                if ext not in IMPORT_EXTS:
                    imports = []
                merged = list(ts_syms)
                seen_names = {s.name for s in merged}
                for sym in regex_syms:
                    if sym.name in seen_names:
                        continue
                    if not sym.end_line:
                        sym.end_line = _infer_symbol_end_line(lines, sym.line)
                    if not sym.signature and 0 < sym.line <= len(lines):
                        sym.signature = lines[sym.line - 1].strip()[:180]
                    merged.append(sym)
                    seen_names.add(sym.name)
                node.symbols = merged
                node.imports = imports
                if ext in IMPORT_EXTS:
                    node.import_records, node.exports = _extract_import_records(lines)
                export_names = set(node.exports)
                for sym in node.symbols:
                    if sym.name in export_names or ('default' in export_names and sym.exported):
                        sym.exported = True
                node.summary = _extract_cortex(lines)
                return node

        # Fallback: regex
        syms, imports = _regex_extract(lines)
        if ext not in IMPORT_EXTS:
            imports = []
        node.symbols = syms
        node.imports = imports
        if ext in IMPORT_EXTS:
            node.import_records, node.exports = _extract_import_records(lines)
        export_names = set(node.exports)
        for sym in node.symbols:
            if not sym.end_line:
                sym.end_line = _infer_symbol_end_line(lines, sym.line)
            if not sym.signature and 0 < sym.line <= len(lines):
                sym.signature = lines[sym.line - 1].strip()[:180]
            if sym.name in export_names:
                sym.exported = True
        node.summary = _extract_cortex(lines)
        return node

# =========================================================================
# ENGINE
# =========================================================================

class IgnoreMatcher:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.patterns: List[str] = []
        self.spec = None
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
        if _HAS_PATHSPEC and self.patterns:
            self.spec = pathspec.PathSpec.from_lines('gitignore', self.patterns)

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


class ImportResolver:
    CODE_EXTS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.php', '.json']

    def __init__(self, root: str, nodes: List[ProjectNode]):
        self.root = os.path.abspath(root)
        self.nodes = {n.id: n for n in nodes}
        self.path_set = set(self.nodes)
        self.tsconfig = TsConfigResolver(root)
        self.composer = ComposerResolver(root)

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

    def resolve(self, source_file: str, specifier: str) -> Optional[str]:
        if not specifier or specifier in ('.', '..'):
            return None
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
        if source_file.endswith('.py') and '.' in specifier:
            resolved = self._try_file(os.path.join(self.root, specifier.replace('.', os.sep)))
            if resolved:
                return resolved
            resolved = self._try_python_module_suffix(specifier)
            if resolved:
                return resolved
        return self._try_file(os.path.join(self.root, specifier))


def _is_probable_external_import(specifier: str) -> bool:
    if not specifier or specifier.startswith('.') or specifier.startswith('/'):
        return False
    if specifier.startswith('@'):
        parts = specifier.split('/')
        return len(parts) <= 2
    return '/' not in specifier


def _pagerank(node_ids: List[str], edges: List[Dict[str, str]], iterations: int = 40, damping: float = 0.85) -> Dict[str, float]:
    if not node_ids:
        return {}
    ids = list(dict.fromkeys(node_ids))
    n = len(ids)
    incoming: Dict[str, List[str]] = {i: [] for i in ids}
    outgoing_count: Dict[str, int] = {i: 0 for i in ids}
    valid = set(ids)
    for edge in edges:
        src, dst = edge.get('source'), edge.get('target')
        if src in valid and dst in valid and src != dst:
            incoming[dst].append(src)
            outgoing_count[src] += 1
    rank = {i: 1.0 / n for i in ids}
    for _ in range(iterations):
        sink = sum(rank[i] for i in ids if outgoing_count[i] == 0)
        new_rank = {}
        for i in ids:
            value = (1 - damping) / n
            value += damping * sink / n
            value += damping * sum(rank[src] / outgoing_count[src] for src in incoming[i] if outgoing_count[src])
            new_rank[i] = value
        rank = new_rank
    max_rank = max(rank.values()) or 1
    return {k: v / max_rank for k, v in rank.items()}

class ArgonEngine:
    def __init__(self, root_dir: str, precision: bool = False, model: str = "gpt-4.1", output_dir: str = ""):
        self.root = os.path.abspath(root_dir)
        self.output_dir = os.path.abspath(output_dir) if output_dir else ''
        self.precision = precision
        self.model = model
        self.token_counter = TokenCounter(model=model, strict=precision)
        self.ignore_matcher = IgnoreMatcher(self.root) if precision else None
        self.extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.sql', '.c', '.cpp', '.h', '.hpp',
            '.java', '.go', '.rs', '.php', '.rb', '.cs', '.sh', '.bat', '.ps1',
            '.md', '.json', '.yaml', '.yml', '.toml', '.ini', '.xml', '.html', '.css',
            '.swift', '.kt', '.scala', '.ex', '.exs', '.lua', '.r', '.jl',
        }
        self.skip_dirs = {
            '__pycache__', '.git', 'node_modules', 'venv', '.venv',
            'dist', 'build', '.next', 'target', '.cache', 'coverage',
            '.pytest_cache', '.argon_cache', 'vendor', 'bin', 'obj', '.idea', '.vs',
        }
        self.skip_files = {
            'argon_graph.json', 'ARGON.md', 'argon_view.html', '.argon_cache.json',
            'argon.py', 'argon_mcp.py', 'argon_view.py', 'argon_watch.py',
            'argon_template.html',
        }
        self.parser = UniversalParser(self.root)

    def _should_skip(self, path: str, is_dir: bool) -> bool:
        name = os.path.basename(path)
        if self.ignore_matcher and self.ignore_matcher.match(path, is_dir):
            return True
        if is_dir:
            return name in self.skip_dirs or (
                name.startswith('.') and name not in ('.cursor', '.github', '.agents')
            )
        try:
            sz = os.path.getsize(path)
        except OSError:
            return True
        return (
            name in self.skip_files or
            name.startswith('ARGON_PRECISION.') or
            os.path.splitext(name)[1].lower() not in self.extensions or
            sz > 2_000_000
        )

    def _cache_path(self) -> str:
        base = self.output_dir if self.output_dir else self.root
        return os.path.join(base, '.argon_cache.json')

    def _load_parse_cache(self) -> Dict[str, Any]:
        try:
            with open(self._cache_path(), 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('files', {}) if data.get('version') == 1 else {}
        except Exception:
            return {}

    def _save_parse_cache(self, cache: Dict[str, Any]) -> None:
        try:
            with open(self._cache_path(), 'w', encoding='utf-8') as f:
                json.dump({'version': 1, 'files': cache}, f, ensure_ascii=False)
        except Exception:
            return

    def _node_from_cache(self, data: Dict[str, Any]) -> ProjectNode:
        node = ProjectNode(
            id=data['id'],
            type=data.get('type', ''),
            lines=data.get('lines', 0),
            size_bytes=data.get('size_bytes', 0),
            imports=data.get('imports', []),
            import_records=data.get('import_records', []),
            exports=data.get('exports', []),
            unresolved_imports=data.get('unresolved_imports', []),
            resolved_imports=data.get('resolved_imports', {}),
            summary=data.get('summary', ''),
            importance=data.get('importance', 0.0),
            pagerank=data.get('pagerank', 0.0),
        )
        node.symbols = [Symbol(**sym) for sym in data.get('symbols', [])]
        return node

    def _compute_importance(self, nodes: List[ProjectNode], edges: List[Dict]) -> None:
        ranks = _pagerank([n.id for n in nodes], edges) if self.precision else {}
        conn: Dict[str, int] = defaultdict(int)
        for e in edges:
            conn[e['source']] += 1
            conn[e['target']] += 1
        max_c = max(conn.values()) if conn else 1
        max_l = max((n.lines for n in nodes), default=1) or 1
        max_s = max((len(n.symbols) for n in nodes), default=1) or 1
        for n in nodes:
            c = conn.get(n.id, 0) / max_c
            l = n.lines / max_l
            s = len(n.symbols) / max_s
            n.pagerank = round(ranks.get(n.id, 0.0), 6)
            if self.precision:
                n.importance = round((n.pagerank * 0.7) + (c * 0.2) + (s * 0.1), 4)
            else:
                n.importance = round(c * 0.6 + l * 0.3 + s * 0.1, 4)

    def build_graph(self) -> Dict[str, Any]:
        nodes: List[ProjectNode] = []
        print(f"[*] ARGON v9.0 — Escaneando: {self.root}")
        print(f"[*] Parser: {self.parser.mode.upper()}")
        parse_cache = self._load_parse_cache()
        next_cache: Dict[str, Any] = {}
        cache_hits = 0

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if not self._should_skip(os.path.join(dirpath, d), True)
            ]
            for f in filenames:
                fpath = os.path.join(dirpath, f)
                if self._should_skip(fpath, False):
                    continue
                rel = os.path.relpath(fpath, self.root).replace('\\', '/')
                try:
                    stat = os.stat(fpath)
                except OSError:
                    continue
                cached = parse_cache.get(rel)
                if cached and cached.get('mtime') == stat.st_mtime and cached.get('size') == stat.st_size:
                    node = self._node_from_cache(cached['node'])
                    cache_hits += 1
                else:
                    node = self.parser.parse(fpath)
                nodes.append(node)
                next_cache[rel] = {'mtime': stat.st_mtime, 'size': stat.st_size, 'node': node.to_dict()}

        edges = []
        seen_edges: Set[tuple] = set()

        if self.precision:
            resolver = ImportResolver(self.root, nodes)
            for n in nodes:
                records = n.import_records or [{'source': imp, 'line': 0, 'names': [], 'kind': 'import'} for imp in n.imports]
                for record in records:
                    imp = record.get('source', '')
                    target = resolver.resolve(n.id, imp)
                    if target:
                        n.resolved_imports[imp] = target
                        edge = (n.id, target)
                        if edge not in seen_edges:
                            edges.append({
                                'source': n.id,
                                'target': target,
                                'import': imp,
                                'line': record.get('line', 0),
                                'kind': record.get('kind', 'import'),
                                'names': record.get('names', []),
                                'specifiers': record.get('specifiers', []),
                            })
                            seen_edges.add(edge)
                    elif imp and not imp.startswith(('http://', 'https://')):
                        if _is_probable_external_import(imp):
                            continue
                        root = imp.split('/')[0].lstrip('@')
                        if root.lower() not in STDLIB_NOISE:
                            n.unresolved_imports.append(imp)
        else:
            # === O(N) edge builder with hash index ===
            node_ids = {n.id for n in nodes}
            path_index: Dict[str, Set[str]] = defaultdict(set)
            for nid in node_ids:
                base = nid.rsplit('.', 1)[0]
                path_index[base].add(nid)
                path_index[base.split('/')[-1]].add(nid)

            AMBIGUOUS_NAMES = {'utils', 'helpers', 'config', 'types', 'index', 'main', 'constants', 'common', 'models', 'views'}

            for n in nodes:
                n_dir = '/'.join(n.id.split('/')[:-1])
                for imp in n.imports:
                    clean = imp.replace('.', '/').strip('/')
                    imp_base = clean.split('/')[-1]
                    candidates = set()
                    if clean in path_index:
                        candidates |= path_index[clean]
                    if imp_base in path_index:
                        candidates |= path_index[imp_base]

                    scored = []
                    for tid in candidates:
                        if tid == n.id:
                            continue
                        tb = tid.rsplit('.', 1)[0]
                        if tb.endswith(clean) or tb == clean or clean == tb.split('/')[-1]:
                            td = '/'.join(tid.split('/')[:-1])
                            if td == n_dir:
                                scored.append((3, tid))
                            elif td.startswith(n_dir) or n_dir.startswith(td):
                                scored.append((2, tid))
                            else:
                                scored.append((1, tid))

                    if scored:
                        scored.sort(key=lambda x: x[0], reverse=True)
                        if len(scored) > 1 and imp_base in AMBIGUOUS_NAMES:
                            scored = scored[:1]
                        for _, tid in scored:
                            edge = (n.id, tid)
                            if edge not in seen_edges:
                                edges.append({'source': n.id, 'target': tid})
                                seen_edges.add(edge)

        # Compute importance
        self._compute_importance(nodes, edges)

        symbol_nodes = self._build_symbol_graph(nodes, edges) if self.precision else []
        symbol_edges = self._resolve_symbol_edges(nodes, edges)[0] if self.precision else []
        symbol_calls = [e for e in symbol_edges if e.get('kind') in ('calls-symbol', 'calls-symbol-local')]
        symbol_calls_imported = [e for e in symbol_edges if e.get('kind') == 'calls-symbol']
        symbol_calls_local = [e for e in symbol_edges if e.get('kind') == 'calls-symbol-local']

        graph = {
            'root': os.path.basename(self.root),
            'nodes': [n.to_dict() for n in nodes],
            'edges': edges,
            'symbols': symbol_nodes,
            'symbol_edges': symbol_edges,
            'parser_mode': self.parser.mode,
            'precision': self.precision,
            'model': self.model,
            'stats': {
                'total_files': len(nodes),
                'total_connections': len(edges),
                'total_symbols': sum(len(n.symbols) for n in nodes),
                'total_symbol_connections': len(symbol_edges),
                'total_symbol_calls': len(symbol_calls),
                'total_symbol_calls_imported': len(symbol_calls_imported),
                'total_symbol_calls_local': len(symbol_calls_local),
                'unresolved_imports': sum(len(n.unresolved_imports) for n in nodes),
                'cache_hits': cache_hits,
                'timestamp': str(datetime.datetime.now()),
            }
        }
        self._save_parse_cache(next_cache)
        return graph

    def _build_symbol_graph(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        symbol_edges, resolved_counts = self._resolve_symbol_edges(nodes, edges)
        incoming_by_file: Dict[str, int] = defaultdict(int)
        imported_names: Dict[str, int] = defaultdict(int)
        inbound_calls: Dict[str, int] = defaultdict(int)
        outbound_calls: Dict[str, int] = defaultdict(int)
        inbound_calls_local: Dict[str, int] = defaultdict(int)
        outbound_calls_local: Dict[str, int] = defaultdict(int)
        for edge in edges:
            incoming_by_file[edge['target']] += 1
        for edge in symbol_edges:
            if edge.get('kind') == 'calls-symbol':
                inbound_calls[edge['target']] += 1
                outbound_calls[edge['source']] += 1
            elif edge.get('kind') == 'calls-symbol-local':
                inbound_calls_local[edge['target']] += 1
                outbound_calls_local[edge['source']] += 1
                # Also count towards total inbound/outbound
                inbound_calls[edge['target']] += 1
                outbound_calls[edge['source']] += 1
            else:
                imported_names[edge['target']] += 1

        symbols: List[Dict[str, Any]] = []
        file_rank = {n.id: n.pagerank or n.importance for n in nodes}
        for node in nodes:
            for sym in node.symbols:
                sid = f"{node.id}::{sym.name}"
                imported = imported_names.get(sid, 0)
                total_inbound = inbound_calls.get(sid, 0)
                rank = file_rank.get(node.id, 0) * 0.50
                rank += (1.0 if sym.exported else 0.0) * 0.20
                rank += min(imported, 5) / 5 * 0.10
                rank += min(total_inbound, 8) / 8 * 0.20  # Calls now weight more
                symbols.append({
                    'id': sid,
                    'name': sym.name,
                    'kind': sym.kind,
                    'file': node.id,
                    'start_line': sym.line,
                    'end_line': sym.end_line or sym.line,
                    'signature': sym.signature,
                    'exported': sym.exported,
                    'rank': round(rank, 6),
                    'incoming_file_imports': incoming_by_file.get(node.id, 0),
                    'named_imports': imported,
                    'resolved_imports': resolved_counts.get(sid, 0),
                    'inbound_calls': inbound_calls.get(sid, 0),
                    'inbound_calls_local': inbound_calls_local.get(sid, 0),
                    'outbound_calls': outbound_calls.get(sid, 0),
                    'outbound_calls_local': outbound_calls_local.get(sid, 0),
                })
        symbols.sort(key=lambda s: s['rank'], reverse=True)
        return symbols

    def _direct_export_index(self, nodes: List[ProjectNode]) -> Dict[str, Dict[str, str]]:
        index: Dict[str, Dict[str, str]] = defaultdict(dict)
        for node in nodes:
            export_names = set(node.exports)
            if node.id.endswith('.py') and not export_names:
                exported_symbols = [s for s in node.symbols if not s.name.startswith('_')]
            else:
                exported_symbols = [s for s in node.symbols if s.exported or s.name in export_names]
            for sym in exported_symbols:
                sid = f"{node.id}::{sym.name}"
                index[node.id][sym.name] = sid
                if 'default' in export_names and sym.exported:
                    index[node.id].setdefault('default', sid)
            if 'default' in export_names and exported_symbols:
                index[node.id].setdefault('default', f"{node.id}::{exported_symbols[0].name}")
        return index

    def _resolved_export_index(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        exports = {file: dict(names) for file, names in self._direct_export_index(nodes).items()}
        for node in nodes:
            exports.setdefault(node.id, {})
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge.get('kind') != 're-export':
                    continue
                source_file = edge['source']
                target_file = edge['target']
                target_exports = exports.get(target_file, {})
                specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
                for spec in specifiers:
                    imported = spec.get('imported')
                    local = spec.get('local') or imported
                    if imported == '*':
                        for name, sid in target_exports.items():
                            if name not in exports[source_file]:
                                exports[source_file][name] = sid
                                changed = True
                    elif imported in target_exports and exports[source_file].get(local) != target_exports[imported]:
                        exports[source_file][local] = target_exports[imported]
                        changed = True
        return exports

    def _source_symbol_ids(self, node: ProjectNode) -> List[str]:
        exported = [s for s in node.symbols if s.exported]
        chosen = exported or node.symbols[:1]
        return [f"{node.id}::{s.name}" for s in chosen]

    def _symbol_source(self, node: ProjectNode, sym: Symbol) -> str:
        path = os.path.join(self.root, node.id)
        content = self.parser.safe_read(path)
        if not content:
            return ""
        lines = content.splitlines()
        start = max(1, sym.line)
        end = max(start, sym.end_line or sym.line)
        if end == start and start <= len(lines):
            end = _infer_symbol_end_line(lines, start)
        return "\n".join(lines[start - 1:end])

    def _local_import_targets(self, edge: Dict[str, Any], exports: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
        target_exports = exports.get(edge['target'], {})
        specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
        targets: List[Dict[str, str]] = []
        for spec in specifiers:
            imported = spec.get('imported')
            local = spec.get('local') or imported
            if imported == '*':
                targets.append({'local': local, 'target': '*', 'imported': '*'})
                continue
            target_sid = target_exports.get(imported)
            if target_sid:
                targets.append({'local': local, 'target': target_sid, 'imported': imported})
        return targets

    def _detect_symbol_calls(
        self,
        nodes: List[ProjectNode],
        edges: List[Dict[str, Any]],
        exports: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        node_by_id = {n.id: n for n in nodes}
        symbols_by_file_name: Dict[str, Dict[str, str]] = defaultdict(dict)
        for node in nodes:
            for sym in node.symbols:
                symbols_by_file_name[node.id][sym.name] = f"{node.id}::{sym.name}"

        imports_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            if edge.get('kind') != 'import':
                continue
            imports_by_file[edge['source']].extend(self._local_import_targets(edge, exports))

        call_edges: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, str]] = set()

        for node in nodes:
            # --- Imported symbol call detection (original) ---
            local_targets = imports_by_file.get(node.id, [])
            # --- Intra-file (local) symbol call detection (Phase 1) ---
            local_symbol_map: Dict[str, str] = {}
            for sym in node.symbols:
                local_symbol_map[sym.name] = f"{node.id}::{sym.name}"

            # Precompile call patterns for all callable names in this file's scope
            callable_targets: List[Tuple[str, str, str, bool]] = []  # (name, target_sid, target_file, is_local)
            for target in local_targets:
                local = target.get('local', '')
                if local and local != '*' and target.get('target'):
                    callable_targets.append((local, target['target'], target['target'].split('::', 1)[0], False))
            for sym_name, sym_sid in local_symbol_map.items():
                callable_targets.append((sym_name, sym_sid, node.id, True))

            qualified_targets: Dict[Tuple[str, str], Tuple[str, str, bool]] = {}
            for target in local_targets:
                local = target.get('local', '')
                target_sid = target.get('target', '')
                if not local or not target_sid:
                    continue
                if target_sid == '*':
                    target_file = next(
                        (
                            edge.get('target')
                            for edge in edges
                            if edge.get('source') == node.id
                            and any(spec.get('local') == local and spec.get('imported') == '*' for spec in edge.get('specifiers', []))
                        ),
                        '',
                    )
                else:
                    target_file = target_sid.split('::', 1)[0]
                if not target_file:
                    continue
                for member_name, member_sid in symbols_by_file_name.get(target_file, {}).items():
                    qualified_targets[(local, member_name)] = (member_sid, target_file, False)

            for qualifier_name in local_symbol_map:
                for member_name, member_sid in symbols_by_file_name.get(node.id, {}).items():
                    qualified_targets[(qualifier_name, member_name)] = (member_sid, node.id, True)
            for implicit_receiver in ('self', 'this'):
                for member_name, member_sid in symbols_by_file_name.get(node.id, {}).items():
                    qualified_targets[(implicit_receiver, member_name)] = (member_sid, node.id, True)

            if not callable_targets:
                if not qualified_targets:
                    continue

            for sym in node.symbols:
                source_sid = f"{node.id}::{sym.name}"
                body = self._symbol_source(node, sym)
                if not body:
                    continue
                for (qualifier, member_name), (target_sid, target_file, is_local) in qualified_targets.items():
                    if target_sid == source_sid:
                        continue
                    qualified_pat = re.compile(
                        rf'\b{re.escape(qualifier)}\s*(?:\([^)]*\))?\s*\.\s*{re.escape(member_name)}\s*\('
                    )
                    if not qualified_pat.search(body):
                        continue
                    key = (source_sid, target_sid, f'{qualifier}.{member_name}')
                    if key not in seen:
                        call_edges.append({
                            'source': source_sid,
                            'target': target_sid,
                            'imported': member_name,
                            'local': f'{qualifier}.{member_name}',
                            'source_file': node.id,
                            'target_file': target_file,
                            'line': sym.line,
                            'kind': 'calls-symbol-local' if is_local else 'calls-symbol',
                            'qualified': True,
                        })
                        seen.add(key)

                for callee_name, target_sid, target_file, is_local in callable_targets:
                    # Don't record self-calls (a function calling itself is recursion, not a dependency edge)
                    if target_sid == source_sid:
                        continue
                    call_pat = re.compile(rf'\b{re.escape(callee_name)}\s*\(')
                    if not call_pat.search(body):
                        continue
                    key = (source_sid, target_sid, callee_name)
                    if key not in seen:
                        call_edges.append({
                            'source': source_sid,
                            'target': target_sid,
                            'imported': callee_name if not is_local else callee_name,
                            'local': callee_name,
                            'source_file': node.id,
                            'target_file': target_file,
                            'line': sym.line,
                            'kind': 'calls-symbol' if not is_local else 'calls-symbol-local',
                        })
                        seen.add(key)
        return call_edges

    def _resolve_symbol_edges(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        node_by_id = {n.id: n for n in nodes}
        exports = self._resolved_export_index(nodes, edges)
        symbol_edges: List[Dict[str, Any]] = []
        resolved_counts: Dict[str, int] = defaultdict(int)
        seen: Set[Tuple[str, str, str]] = set()

        for edge in edges:
            if edge.get('kind') == 're-export':
                continue
            source_node = node_by_id.get(edge['source'])
            if not source_node:
                continue
            source_symbols = self._source_symbol_ids(source_node)
            if not source_symbols:
                continue
            target_exports = exports.get(edge['target'], {})
            specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
            if not specifiers:
                continue
            for spec in specifiers:
                imported = spec.get('imported')
                if imported == '*':
                    target_ids = list(target_exports.values())
                else:
                    target = target_exports.get(imported)
                    target_ids = [target] if target else []
                for source_sid in source_symbols:
                    for target_sid in target_ids:
                        key = (source_sid, target_sid, imported or '', spec.get('local', imported) or '')
                        if target_sid and key not in seen:
                            symbol_edges.append({
                                'source': source_sid,
                                'target': target_sid,
                                'imported': imported,
                                'local': spec.get('local', imported),
                                'source_file': edge['source'],
                                'target_file': edge['target'],
                                'line': edge.get('line', 0),
                                'kind': 'imports-symbol',
                            })
                            resolved_counts[target_sid] += 1
                            seen.add(key)
        symbol_edges.extend(self._detect_symbol_calls(nodes, edges, exports))
        return symbol_edges, resolved_counts

    def generate_context_report(self, graph: Dict[str, Any], output_path: str, max_tokens: int = 4096):
        """Genera ARGON.md con token budget."""
        header = [
            f"# ARGON PROJECT CONTEXT: {graph['root']}",
            f"Generated: {graph['stats']['timestamp']}",
            f"Files: {graph['stats']['total_files']} | Connections: {graph['stats']['total_connections']}",
            f"Parser: {graph.get('parser_mode', 'regex')}",
            "", "---", "",
        ]
        header_text = "\n".join(header)
        budget = max_tokens - estimate_tokens(header_text)

        # Sort by importance
        sorted_nodes = sorted(graph['nodes'], key=lambda x: x.get('importance', 0), reverse=True)

        detailed = []
        summary_only = []
        used = 0

        for n in sorted_nodes:
            block_lines = [f"### {n['id']} [{n['type'].upper()} | {n['lines']}L | imp:{n.get('importance', 0):.2f}]"]
            if n.get('summary'):
                block_lines.append(f"> {n['summary']}")
            syms = [f"{s['kind']}:{s['name']}" for s in n.get('symbols', [])]
            if syms:
                block_lines.append(f"- SYMBOLS: {', '.join(syms[:20])}")
            imps = list(dict.fromkeys(n.get('imports', [])))
            if imps:
                block_lines.append(f"- DEPENDS: {', '.join(imps[:10])}")
            block_lines.append("")
            block_text = "\n".join(block_lines)
            cost = estimate_tokens(block_text)

            if used + cost <= budget:
                detailed.append(block_text)
                used += cost
            else:
                summary_only.append(n['id'])

        parts = [header_text] + detailed
        if summary_only:
            remaining = f"\n---\n\n## REMAINING FILES ({len(summary_only)})\n"
            remaining += "\n".join(f"- {p}" for p in summary_only[:200])
            if len(summary_only) > 200:
                remaining += f"\n- ... +{len(summary_only) - 200} more"
            parts.append(remaining)

        output = "\n".join(parts)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)

        total_tokens = estimate_tokens(output)
        detailed_count = len(detailed)
        print(f"[+] ARGON.md: {detailed_count} detailed + {len(summary_only)} listed | ~{total_tokens} tokens")

    def _read_symbol_snippet(self, symbol: Dict[str, Any], max_lines: int = 80) -> str:
        path = os.path.join(self.root, symbol['file'])
        content = self.parser.safe_read(path)
        if not content:
            return ""
        lines = content.splitlines()
        start = max(1, int(symbol.get('start_line') or 1))
        end = max(start, int(symbol.get('end_line') or start))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
        return "\n".join(lines[start - 1:end])

    def _task_keywords(self, task: str) -> List[str]:
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'and', 'or', 'not', 'this', 'that', 'it', 'i', 'we', 'you', 'need', 'want', 'make', 'add',
            'when', 'while', 'during', 'after', 'before',
            'fix', 'update', 'change', 'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en', 'con',
            'por', 'para', 'que', 'como', 'es', 'son', 'hay', 'quiero', 'necesito', 'hacer', 'crear',
            'modificar', 'arreglar',
        }
        words: List[str] = []
        for raw in re.findall(r'[\w@./-]+', task):
            words.extend(self._identifier_tokens(raw))
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]
        expanded: List[str] = []
        synonym_groups = {
            'auth': {
                'auth', 'authenticate', 'authentication', 'authenticated', 'authorise',
                'authorize', 'authorization', 'login', 'logins', 'logged', 'logs', 'signin', 'session',
            },
            'login': {'login', 'logins', 'logged', 'logs', 'signin', 'auth', 'authenticate', 'authentication'},
            'payment': {'payment', 'pay', 'paid', 'transaction', 'transactions', 'refund', 'refunded'},
            'cache': {'cache', 'cached', 'caching', 'invalidation', 'invalidate', 'invalidated'},
            'order': {'order', 'orders', 'checkout', 'cart'},
            'placement': {'placement', 'place', 'placing', 'submit'},
            'cancel': {'cancel', 'cancellation', 'cancelled', 'canceled'},
            'total': {'total', 'sum', 'price', 'amount', 'calculate', 'calculation'},
        }
        reverse_synonyms: Dict[str, List[str]] = defaultdict(list)
        for canonical, aliases in synonym_groups.items():
            for alias in aliases:
                if canonical not in reverse_synonyms[alias]:
                    reverse_synonyms[alias].append(canonical)
        for word in keywords:
            expanded.append(word)
            for canonical in reverse_synonyms.get(word, []):
                expanded.append(canonical)
                if canonical in {'total', 'placement'}:
                    expanded.extend(sorted(synonym_groups.get(canonical, [])))
        return list(dict.fromkeys(expanded))

    def _identifier_tokens(self, text: str) -> List[str]:
        text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
        text = re.sub(r'[@./_\-]+', ' ', text)
        return [p.lower() for p in re.findall(r'[A-Za-z0-9]+', text)]

    def _symbol_tokens(self, sym: Dict[str, Any]) -> Set[str]:
        chunks = [
            sym.get('id', ''),
            sym.get('name', ''),
            sym.get('file', ''),
            sym.get('kind', ''),
            sym.get('signature', ''),
        ]
        out: List[str] = []
        for chunk in chunks:
            out.extend(self._identifier_tokens(str(chunk)))
        return set(out)

    def _symbol_match_profile(self, sym: Dict[str, Any], keywords: List[str]) -> Dict[str, Set[str]]:
        task_tokens = set(keywords)
        return {
            'name': task_tokens & set(self._identifier_tokens(sym.get('name', ''))),
            'file': task_tokens & set(self._identifier_tokens(sym.get('file', ''))),
            'signature': task_tokens & set(self._identifier_tokens(sym.get('signature', ''))),
            'all': task_tokens & self._symbol_tokens(sym),
        }

    def _is_noise_symbol_for_task(self, sym: Dict[str, Any]) -> bool:
        name = str(sym.get('name', ''))
        signature = str(sym.get('signature', '')).strip()
        if name in SYMBOL_NOISE:
            return True
        if signature.startswith(('raise ', 'throw new ')) and name.endswith('Error'):
            return True
        declaration_prefixes = (
            'def ', 'async def ', 'class ', 'export ', 'function ', 'async function ',
            'const ', 'let ', 'var ', 'interface ', 'type ', 'enum ',
            'public ', 'private ', 'protected ', 'static ', 'final ', 'void ',
            'boolean ', 'string ', 'int ', 'long ', 'double ', 'float ', 'decimal ',
            'namespace ', 'using ',
        )
        if (
            str(sym.get('kind', '')).lower() == 'func'
            and signature
            and not signature.startswith(declaration_prefixes)
            and (
                int(sym.get('start_line') or 0) == int(sym.get('end_line') or 0)
                or signature.endswith(')')
                or ('{' not in signature and '=>' not in signature and not signature.endswith(':'))
            )
            and not sym.get('exported')
        ):
            return True
        return False

    def _symbol_token_cost(self, sym: Dict[str, Any], include_code: bool = True) -> int:
        snippet = self._read_symbol_snippet(sym) if include_code else ""
        preview = {
            'id': sym.get('id', ''),
            'file': sym.get('file', ''),
            'kind': sym.get('kind', ''),
            'signature': sym.get('signature', ''),
            'reasons': sym.get('selection_reasons', []),
            'code': snippet,
        }
        return max(1, self.token_counter.count(json.dumps(preview, ensure_ascii=False)))

    def _task_intents(self, task: str) -> Set[str]:
        tokens = set(self._task_keywords(task))
        intents = set()
        if tokens & {'bug', 'fix', 'fail', 'failure', 'error', 'regression', 'broken', 'arreglar', 'fallo'}:
            intents.add('bugfix')
        if tokens & {'test', 'tests', 'spec', 'coverage', 'regression', 'prueba', 'pruebas'}:
            intents.add('tests')
        if tokens & {'type', 'types', 'interface', 'schema', 'model', 'typing', 'tipo', 'tipos'}:
            intents.add('types')
        return intents

    def _task_focus_tokens(self, keywords: List[str]) -> Set[str]:
        entity_tokens = {
            'user', 'users', 'order', 'orders', 'item', 'items', 'model', 'models',
            'data', 'support', 'bug', 'wrong', 'empty', 'strategy',
        }
        return {kw for kw in keywords if kw not in entity_tokens}

    def _is_generic_type_symbol(self, sym: Dict[str, Any]) -> bool:
        kind = str(sym.get('kind', '')).lower()
        if kind not in {'symbol', 'interface', 'type', 'enum', 'struct'}:
            return False
        return (
            int(sym.get('named_imports') or 0) >= 25 and
            int(sym.get('inbound_calls') or 0) == 0
        )

    def _edge_maps(self, graph: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
        incoming: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        outgoing: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in graph.get('symbol_edges', []):
            source = edge.get('source')
            target = edge.get('target')
            if source and target:
                outgoing[source].append(edge)
                incoming[target].append(edge)
        return incoming, outgoing

    def _score_symbol_for_task(self, sym: Dict[str, Any], keywords: List[str]) -> Tuple[float, int]:
        if not keywords:
            return 0.0, 0
        profile = self._symbol_match_profile(sym, keywords)
        overlap = profile['all']
        score = 0.0
        score += len(profile['name']) * 5.0
        score += len(profile['file']) * 1.6
        score += len(profile['signature']) * 1.5
        score += max(0, len(overlap) - len(profile['name'])) * 0.6
        focus_tokens = self._task_focus_tokens(keywords)
        if (
            focus_tokens & profile['file']
            and str(sym.get('kind', '')).lower() == 'func'
            and sym.get('exported')
            and 'test' not in str(sym.get('file', '')).lower()
            and 'spec' not in str(sym.get('file', '')).lower()
        ):
            score += 1.2

        lower_name = sym.get('name', '').lower()
        lower_file = sym.get('file', '').lower()
        for kw in keywords:
            if kw in lower_name:
                score += 1.5
            if kw in lower_file:
                score += 0.45
        return score, len(overlap)

    def _is_weak_file_only_match(self, sym: Dict[str, Any], keywords: List[str]) -> bool:
        profile = self._symbol_match_profile(sym, keywords)
        if profile['name'] or profile['signature']:
            return False
        if not profile['file']:
            return False
        return True

    def _is_unrequested_test_symbol(self, sym: Dict[str, Any], intents: Set[str]) -> bool:
        if 'tests' in intents:
            return False
        file_path = str(sym.get('file', '')).lower().replace('\\', '/')
        return '/test' in f'/{file_path}' or file_path.endswith('_test.py') or file_path.endswith('.test.ts')

    def _is_isolated_focus_match(self, sym: Dict[str, Any], keywords: List[str]) -> bool:
        profile = self._symbol_match_profile(sym, keywords)
        focus_tokens = self._task_focus_tokens(keywords)
        if not (focus_tokens & (profile['name'] | profile['signature'])):
            return False
        structural_signal = (
            int(sym.get('inbound_calls') or 0)
            + int(sym.get('outbound_calls') or 0)
            + int(sym.get('named_imports') or 0)
            + int(sym.get('resolved_imports') or 0)
        )
        if structural_signal > 0:
            return False
        file_path = str(sym.get('file', '')).lower().replace('\\', '/')
        distractor_segments = {'noise', 'noisy', 'mock', 'mocks', 'sample', 'samples', 'fixture', 'fixtures'}
        return any(f'/{segment}/' in f'/{file_path}' for segment in distractor_segments)

    def _support_symbol_factor(self, sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> float:
        focus_tokens = self._task_focus_tokens(keywords)
        file_path = str(sym.get('file', '')).lower()
        if 'tests' not in intents and ('test' in file_path or 'spec' in file_path):
            return 0.55
        if not focus_tokens:
            return 1.0
        profile = self._symbol_match_profile(sym, keywords)
        focus_overlap = focus_tokens & profile['all']
        if focus_overlap:
            return 1.0

        kind = str(sym.get('kind', '')).lower()
        name = str(sym.get('name', ''))
        is_model = '/models/' in file_path or '\\models\\' in file_path or kind in {'class', 'interface', 'type', 'enum', 'struct'}
        if is_model:
            return 0.25
        if profile['all'] and not focus_overlap:
            return 0.58
        if name and name[:1].isupper() and not profile['name']:
            return 0.70
        return 1.0

    def _context_tier(self, sym: Dict[str, Any], keywords: List[str], intents: Set[str]) -> str:
        profile = self._symbol_match_profile(sym, keywords)
        focus_tokens = self._task_focus_tokens(keywords)
        focus_name_or_signature = focus_tokens & (profile['name'] | profile['signature'])
        file_path = str(sym.get('file', '')).lower()
        kind = str(sym.get('kind', '')).lower()
        is_test = 'test' in file_path or 'spec' in file_path
        is_model = '/models/' in file_path or '\\models\\' in file_path or kind in {'class', 'interface', 'type', 'enum', 'struct'}
        is_func = kind == 'func'
        structural_signal = int(sym.get('inbound_calls') or 0) + int(sym.get('outbound_calls') or 0)

        if is_test:
            return 'workflow' if 'tests' in intents else 'support'
        if is_func and focus_name_or_signature:
            return 'critical'
        if is_func and not is_model and (focus_tokens & profile['file'] and sym.get('exported')):
            return 'critical'
        if is_func and not is_model and profile['all'] and structural_signal > 0:
            return 'workflow'
        return 'support'

    def _neighbor_score(self, sym_id: str, base_score: float, default_factor: float, symbols: Dict[str, Dict[str, Any]], keywords: List[str]) -> float:
        sym = symbols.get(sym_id)
        if not sym:
            return 0.0
        task_score, overlap_count = self._score_symbol_for_task(sym, keywords)
        if overlap_count:
            factor = default_factor
        elif task_score > 0:
            factor = default_factor * 0.75
        else:
            factor = min(default_factor, 0.035)
        return max(base_score * factor, task_score * 0.35)

    def _select_precision_symbols(self, graph: Dict[str, Any], task: str) -> List[Dict[str, Any]]:
        keywords = self._task_keywords(task)
        intents = self._task_intents(task)
        symbols = {s['id']: s for s in graph.get('symbols', [])}
        incoming, outgoing = self._edge_maps(graph)
        candidates: Dict[str, Dict[str, Any]] = {}
        report = {
            'keywords': keywords,
            'intents': sorted(intents),
            'direct_matches': 0,
            'callers': 0,
            'callees': 0,
            'import_neighbors': 0,
            'tests': 0,
            'global_fallback': 0,
            'generic_types_penalized': 0,
        }

        def add(sym_id: str, score: float, reason: str) -> None:
            sym = symbols.get(sym_id)
            if not sym:
                return
            if self._is_noise_symbol_for_task(sym):
                report['noise_symbols_filtered'] = report.get('noise_symbols_filtered', 0) + 1
                return
            if self._is_unrequested_test_symbol(sym, intents):
                report['unrequested_tests_filtered'] = report.get('unrequested_tests_filtered', 0) + 1
                return
            if 'bugfix' not in intents and self._is_weak_file_only_match(sym, keywords):
                report['weak_file_matches_filtered'] = report.get('weak_file_matches_filtered', 0) + 1
                return
            if reason in {'callers', 'callees', 'import_neighbors'}:
                profile = self._symbol_match_profile(sym, keywords)
                tier = self._context_tier(sym, keywords, intents)
                kind = str(sym.get('kind', '')).lower()
                structural_model = kind in {'class', 'interface', 'type', 'enum', 'struct'}
                if tier == 'support' and not profile['all'] and not structural_model:
                    report['non_task_neighbors_filtered'] = report.get('non_task_neighbors_filtered', 0) + 1
                    return
            current = candidates.get(sym_id)
            if current is None:
                item = dict(sym)
                item['selection_score'] = round(score, 6)
                item['selection_reasons'] = [reason]
                item['task_token_overlap'] = sorted(set(keywords) & self._symbol_tokens(sym))
                item['context_tier'] = self._context_tier(sym, keywords, intents)
                candidates[sym_id] = item
                if reason in report:
                    report[reason] += 1
                return
            if score > current.get('selection_score', 0):
                current['selection_score'] = round(score, 6)
            if reason not in current['selection_reasons']:
                current['selection_reasons'].append(reason)
                if reason in report:
                    report[reason] += 1

        seed_scores = []
        for sym in graph.get('symbols', []):
            task_score, overlap_count = self._score_symbol_for_task(sym, keywords)
            generic = self._is_generic_type_symbol(sym)
            generic_penalty = 0.45 if generic and overlap_count == 0 and 'types' not in intents else 1.0
            if generic_penalty < 1:
                report['generic_types_penalized'] += 1
            graph_score = float(sym.get('rank', 0))
            call_score = min(int(sym.get('inbound_calls') or 0), 8) / 8
            support_factor = self._support_symbol_factor(sym, keywords, intents)
            if support_factor < 1:
                report['support_symbols_demoted'] = report.get('support_symbols_demoted', 0) + 1
            final = ((task_score * 0.55) + (call_score * 0.25) + (graph_score * 0.20)) * generic_penalty * support_factor
            if task_score > 0:
                if self._is_noise_symbol_for_task(sym):
                    report['noise_symbols_filtered'] = report.get('noise_symbols_filtered', 0) + 1
                    continue
                if self._is_unrequested_test_symbol(sym, intents):
                    report['unrequested_tests_filtered'] = report.get('unrequested_tests_filtered', 0) + 1
                    continue
                if 'bugfix' not in intents and self._is_weak_file_only_match(sym, keywords):
                    report['weak_file_matches_filtered'] = report.get('weak_file_matches_filtered', 0) + 1
                    continue
                if self._is_isolated_focus_match(sym, keywords):
                    report['isolated_focus_matches_filtered'] = report.get('isolated_focus_matches_filtered', 0) + 1
                    continue
                seed_scores.append((final, task_score, sym['id']))
                add(sym['id'], final, 'direct_matches')

        seed_scores.sort(reverse=True)
        seeds = seed_scores[:40]

        for seed_final, _, seed_id in seeds:
            for edge in incoming.get(seed_id, []):
                source = edge.get('source')
                if edge.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                    add(source, seed_final * 0.70, 'callers')
                else:
                    add(source, self._neighbor_score(source, seed_final, 0.35, symbols, keywords), 'import_neighbors')
            for edge in outgoing.get(seed_id, []):
                target = edge.get('target')
                if edge.get('kind') in ('calls-symbol', 'calls-symbol-local'):
                    add(target, seed_final * 0.65, 'callees')
                else:
                    add(target, self._neighbor_score(target, seed_final, 0.30, symbols, keywords), 'import_neighbors')

        if 'bugfix' in intents or 'tests' in intents:
            task_tokens = set(keywords)
            for sym in graph.get('symbols', []):
                file_path = sym.get('file', '').lower()
                if 'test' not in file_path and 'spec' not in file_path:
                    continue
                overlap = task_tokens & self._symbol_tokens(sym)
                if overlap:
                    test_score = 3.0 + len(overlap) if 'tests' in intents else 1.2 + (len(overlap) * 0.5)
                    add(sym['id'], test_score, 'tests')

        if not candidates:
            for sym in graph.get('symbols', [])[:80]:
                if self._is_generic_type_symbol(sym):
                    continue
                add(sym['id'], float(sym.get('rank', 0)) * 0.5, 'global_fallback')

        selected = sorted(
            candidates.values(),
            key=lambda s: (
                {'critical': 3, 'workflow': 2, 'support': 1}.get(s.get('context_tier', 'support'), 1),
                s.get('selection_score', 0),
                s.get('value_per_token', 0),
                s.get('rank', 0),
            ),
            reverse=True,
        )
        for item in selected:
            token_cost = self._symbol_token_cost(item)
            item['token_cost'] = token_cost
            item['value_per_token'] = round(float(item.get('selection_score', 0)) / max(1, token_cost), 6)
        selected.sort(
            key=lambda s: (
                {'critical': 3, 'workflow': 2, 'support': 1}.get(s.get('context_tier', 'support'), 1),
                s.get('selection_score', 0),
                s.get('value_per_token', 0),
                s.get('rank', 0),
            ),
            reverse=True,
        )
        report['selected_candidates'] = len(selected)
        self._last_selection_report = report
        return selected

    def _precision_symbol_block(self, symbol: Dict[str, Any], output_format: str) -> str:
        snippet = self._read_symbol_snippet(symbol)
        if output_format == 'json':
            data = dict(symbol)
            data['code'] = snippet
            return json.dumps(data, ensure_ascii=False, indent=2)
        if output_format == 'xml':
            reasons = ",".join(symbol.get('selection_reasons', []))
            overlap = ",".join(symbol.get('task_token_overlap', []))
            attrs = (
                f'id="{xml_escape(symbol["id"])}" rank="{symbol.get("rank", 0)}" '
                f'selection_score="{symbol.get("selection_score", 0)}" '
                f'value_per_token="{symbol.get("value_per_token", 0)}" '
                f'token_cost="{symbol.get("token_cost", 0)}" '
                f'tier="{xml_escape(symbol.get("context_tier", "support"))}" '
                f'reasons="{xml_escape(reasons)}" overlap="{xml_escape(overlap)}" '
                f'file="{xml_escape(symbol["file"])}" start_line="{symbol.get("start_line", 0)}" '
                f'end_line="{symbol.get("end_line", 0)}" kind="{xml_escape(symbol.get("kind", ""))}"'
            )
            return (
                f'  <symbol {attrs}>\n'
                f'    <name>{xml_escape(symbol.get("name", ""))}</name>\n'
                f'    <signature>{xml_escape(symbol.get("signature", ""))}</signature>\n'
                f'    <code><![CDATA[\n{snippet}\n]]></code>\n'
                f'  </symbol>'
            )
        return (
            f"### {symbol['id']} [rank:{symbol.get('rank', 0):.4f}]\n"
            f"- file: {symbol['file']}:{symbol.get('start_line', 0)}-{symbol.get('end_line', 0)}\n"
            f"- signature: {symbol.get('signature', '')}\n\n"
            f"- why: {', '.join(symbol.get('selection_reasons', [])) or 'ranked fallback'}\n"
            f"- tier: {symbol.get('context_tier', 'support')}\n"
            f"- score: {symbol.get('selection_score', 0)} | value/token: {symbol.get('value_per_token', 0)} | token cost: {symbol.get('token_cost', 0)}\n\n"
            f"```{symbol.get('file', '').rsplit('.', 1)[-1]}\n{snippet}\n```\n"
        )

    def _precision_layers(self, symbols: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        layers = {'critical': [], 'workflow': [], 'support': []}
        for sym in symbols:
            tier = sym.get('context_tier', 'support')
            if tier not in layers:
                tier = 'support'
            layers[tier].append(sym)
        return layers

    def _compact_precision_symbol(self, sym: Dict[str, Any]) -> Dict[str, Any]:
        keep = {
            'id', 'name', 'kind', 'file', 'start_line', 'end_line', 'signature',
            'context_tier', 'selection_score', 'selection_reasons', 'task_token_overlap',
            'rank', 'inbound_calls', 'outbound_calls', 'token_cost', 'value_per_token',
        }
        return {key: value for key, value in sym.items() if key in keep}

    def _precision_expansion_plan(
        self,
        selected: List[Dict[str, Any]],
        full_code_ids: Set[str],
        included_ids: Set[str],
        max_items: int = 8,
    ) -> List[Dict[str, Any]]:
        """Small follow-up queue for incremental context instead of overpacking support."""
        plan: List[Dict[str, Any]] = []
        tier_weight = {'critical': 3, 'workflow': 2, 'support': 1}
        candidates = sorted(
            selected,
            key=lambda sym: (
                sym.get('id') not in included_ids,
                tier_weight.get(sym.get('context_tier', 'support'), 1),
                sym.get('selection_score', 0),
                sym.get('value_per_token', 0),
            ),
            reverse=True,
        )
        for sym in candidates:
            sid = sym.get('id', '')
            if not sid or sid in full_code_ids:
                continue
            tier = sym.get('context_tier', 'support')
            if sid in included_ids:
                reason = 'compact_included_expand_if_needed'
            else:
                reason = 'omitted_due_to_budget'
            if (
                tier == 'support'
                and reason == 'compact_included_expand_if_needed'
                and not sym.get('task_token_overlap')
            ):
                continue
            plan.append({
                'symbol': sid,
                'tier': tier,
                'reason': reason,
                'file': sym.get('file', ''),
                'line': sym.get('start_line', 0),
                'selection_score': sym.get('selection_score', 0),
                'value_per_token': sym.get('value_per_token', 0),
                'expand_with': f'argon_expand_symbol("{sid}")',
            })
            if len(plan) >= max_items:
                break
        return plan

    def _fit_expansion_plan(
        self,
        payload: Dict[str, Any],
        selected: List[Dict[str, Any]],
        max_tokens: int,
        counter: Optional[TokenCounter] = None,
        max_items: int = 8,
    ) -> None:
        counter = counter or self.token_counter
        full_code_ids = {sym.get('id', '') for sym in payload.get('symbols', []) if sym.get('code')}
        included_ids = {sym.get('id', '') for sym in payload.get('symbols', [])}
        plan = self._precision_expansion_plan(selected, full_code_ids, included_ids, max_items=max_items)
        payload['expansion_plan'] = []
        for item in plan:
            trial = dict(payload)
            trial['expansion_plan'] = payload['expansion_plan'] + [item]
            trial_text = json.dumps(trial, ensure_ascii=False, indent=2)
            if counter.count(trial_text) <= max_tokens:
                payload['expansion_plan'].append(item)
                continue
            compact = {
                'symbol': item['symbol'],
                'tier': item['tier'],
                'reason': item['reason'],
                'expand_with': item['expand_with'],
            }
            trial['expansion_plan'] = payload['expansion_plan'] + [compact]
            if counter.count(json.dumps(trial, ensure_ascii=False, indent=2)) <= max_tokens:
                payload['expansion_plan'].append(compact)
            elif not payload['expansion_plan']:
                payload['expansion_plan'].append({
                    'symbol': item['symbol'],
                    'expand_with': item['expand_with'],
                })
                while counter.count(json.dumps(payload, ensure_ascii=False, indent=2)) > max_tokens:
                    payload['expansion_plan'].pop()
                    break
            else:
                break

    def generate_precision_context(
        self,
        graph: Dict[str, Any],
        output_path: str,
        task: str,
        max_tokens: int = 4096,
        output_format: str = 'xml',
        budget_profile: str = 'custom',
    ) -> None:
        max_tokens, budget_settings = resolve_precision_budget(max_tokens, budget_profile)
        output_format = output_format.lower()
        if output_format not in {'xml', 'json', 'markdown'}:
            raise ValueError("--format must be one of: xml, json, markdown")

        selected = self._select_precision_symbols(graph, task)
        selection_report = getattr(self, '_last_selection_report', {})
        used_blocks: List[str] = []
        omitted = 0

        if output_format == 'json':
            payload = {
                'repository': graph['root'],
                'precision': True,
                'task': task,
                'model': self.model,
                'max_tokens': max_tokens,
                'budget_profile': budget_settings['name'],
                'used_tokens': 0,
                'stats': graph['stats'],
                'selection_report': selection_report,
                'packaging_report': {
                    'full_code_symbols': 0,
                    'compact_symbols': 0,
                    'support_compacted_by_default': 0,
                },
                'layers': {'critical': [], 'workflow': [], 'support': []},
                'symbols': [],
                'omitted_symbols': 0,
                'unresolved_imports_summary': {
                    'count': graph['stats'].get('unresolved_imports', 0),
                    'files': [
                        {'file': n['id'], 'count': len(n.get('unresolved_imports', []))}
                        for n in graph['nodes'] if n.get('unresolved_imports')
                    ][:50],
                },
            }
            full_snippet_budget = int(max_tokens * float(budget_settings['full_code_ratio']))
            for sym in selected:
                tier = sym.get('context_tier', 'support')
                full = dict(sym)
                full['code'] = self._read_symbol_snippet(sym)
                compact = self._compact_precision_symbol(sym)
                current_text = json.dumps(payload, ensure_ascii=False, indent=2)
                current_tokens = self.token_counter.count(current_text)

                full_limit = full_snippet_budget
                if tier == 'critical' and payload['packaging_report']['full_code_symbols'] == 0:
                    full_limit = max(full_limit, max_tokens)
                if tier != 'support' and current_tokens < full_limit:
                    trial = dict(payload)
                    trial['symbols'] = payload['symbols'] + [full]
                    trial['layers'] = {
                        tier: ids + ([full['id']] if tier == full.get('context_tier', 'support') else [])
                        for tier, ids in payload['layers'].items()
                    }
                    trial['omitted_symbols'] = omitted
                    trial_text = json.dumps(trial, ensure_ascii=False, indent=2)
                    if self.token_counter.count(trial_text) <= full_limit:
                        payload['symbols'].append(full)
                        payload['layers'].setdefault(full.get('context_tier', 'support'), []).append(full['id'])
                        payload['packaging_report']['full_code_symbols'] += 1
                        continue

                trial = dict(payload)
                trial['symbols'] = payload['symbols'] + [compact]
                trial['layers'] = {
                    tier: ids + ([compact['id']] if tier == compact.get('context_tier', 'support') else [])
                    for tier, ids in payload['layers'].items()
                }
                trial['omitted_symbols'] = omitted
                trial_text = json.dumps(trial, ensure_ascii=False, indent=2)
                if self.token_counter.count(trial_text) <= max_tokens:
                    payload['symbols'].append(compact)
                    payload['layers'].setdefault(compact.get('context_tier', 'support'), []).append(compact['id'])
                    payload['packaging_report']['compact_symbols'] += 1
                    if tier == 'support':
                        payload['packaging_report']['support_compacted_by_default'] += 1
                else:
                    omitted += 1

            payload['omitted_symbols'] = omitted
            output = json.dumps(payload, ensure_ascii=False, indent=2)
            payload['used_tokens'] = self.token_counter.count(output)
            output = json.dumps(payload, ensure_ascii=False, indent=2)
            while self.token_counter.count(output) > max_tokens and payload['symbols']:
                removed = payload['symbols'].pop()
                tier = removed.get('context_tier', 'support')
                if removed.get('id') in payload['layers'].get(tier, []):
                    payload['layers'][tier].remove(removed['id'])
                if removed.get('code'):
                    payload['packaging_report']['full_code_symbols'] = max(0, payload['packaging_report']['full_code_symbols'] - 1)
                else:
                    payload['packaging_report']['compact_symbols'] = max(0, payload['packaging_report']['compact_symbols'] - 1)
                payload['omitted_symbols'] += 1
                payload['used_tokens'] = 0
                output = json.dumps(payload, ensure_ascii=False, indent=2)
                payload['used_tokens'] = self.token_counter.count(output)
                output = json.dumps(payload, ensure_ascii=False, indent=2)

            self._fit_expansion_plan(
                payload,
                selected,
                max_tokens,
                max_items=int(budget_settings['expansion_items']),
            )
            output = json.dumps(payload, ensure_ascii=False, indent=2)
            payload['used_tokens'] = self.token_counter.count(output)
            output = json.dumps(payload, ensure_ascii=False, indent=2)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"[+] Precision context: {output_path} | {self.token_counter.count(output)} tokens")
            return

        if output_format == 'xml':
            header = (
                f'<repository name="{xml_escape(graph["root"])}" precision="true">\n'
                f'  <task>{xml_escape(task)}</task>\n'
                f'  <budget model="{xml_escape(self.model)}" max_tokens="{max_tokens}" profile="{xml_escape(budget_settings["name"])}" />\n'
                f'  <stats files="{graph["stats"]["total_files"]}" connections="{graph["stats"]["total_connections"]}" '
                f'symbols="{graph["stats"].get("total_symbols", 0)}" unresolved_imports="{graph["stats"].get("unresolved_imports", 0)}" />\n'
                f'  <selection direct_matches="{selection_report.get("direct_matches", 0)}" callers="{selection_report.get("callers", 0)}" '
                f'callees="{selection_report.get("callees", 0)}" tests="{selection_report.get("tests", 0)}" '
                f'generic_types_penalized="{selection_report.get("generic_types_penalized", 0)}" />\n'
                f'  <context>\n'
            )
            footer = '  </context>\n</repository>\n'
        else:
            header = (
                f"# ARGON PRECISION CONTEXT: {graph['root']}\n"
                f"Task: {task}\n"
                f"Model: {self.model} | Budget: {max_tokens} | Profile: {budget_settings['name']}\n"
                f"Files: {graph['stats']['total_files']} | Connections: {graph['stats']['total_connections']} | "
                f"Symbols: {graph['stats'].get('total_symbols', 0)} | Unresolved imports: {graph['stats'].get('unresolved_imports', 0)}\n\n"
                f"Selection: direct={selection_report.get('direct_matches', 0)} callers={selection_report.get('callers', 0)} "
                f"callees={selection_report.get('callees', 0)} tests={selection_report.get('tests', 0)} "
                f"generic_penalized={selection_report.get('generic_types_penalized', 0)}\n\n"
            )
            footer = ''

        budget = max_tokens - self.token_counter.count(header + footer)
        used = 0
        layers = self._precision_layers(selected)
        full_code_ids: Set[str] = set()
        included_ids: Set[str] = set()
        for tier in ('critical', 'workflow', 'support'):
            tier_symbols = layers[tier]
            if not tier_symbols:
                continue
            if output_format == 'xml':
                section_open = f'    <layer name="{tier}">\n'
                section_close = f'    </layer>'
            else:
                section_open = f"\n## {tier.upper()}\n"
                section_close = ""
            section_cost = self.token_counter.count(section_open + section_close)
            if used + section_cost <= budget:
                used_blocks.append(section_open.rstrip("\n"))
                used += section_cost
            else:
                omitted += len(tier_symbols)
                continue
            for sym in tier_symbols:
                if tier == 'support':
                    block = (
                        f'  <symbol-ref id="{xml_escape(sym["id"])}" tier="support" file="{xml_escape(sym["file"])}" line="{sym.get("start_line", 0)}" />'
                        if output_format == 'xml'
                        else f"- {sym['id']} ({sym['file']}:{sym.get('start_line', 0)}) [support]\n"
                    )
                else:
                    block = self._precision_symbol_block(sym, output_format)
                cost = self.token_counter.count(block)
                if used + cost <= budget:
                    used_blocks.append(block)
                    used += cost
                    included_ids.add(sym['id'])
                    if tier != 'support':
                        full_code_ids.add(sym['id'])
                else:
                    compact = dict(sym)
                    compact.pop('code', None)
                    compact_block = (
                        json.dumps(compact, ensure_ascii=False)
                        if output_format == 'json'
                        else f'  <symbol-ref id="{xml_escape(sym["id"])}" file="{xml_escape(sym["file"])}" line="{sym.get("start_line", 0)}" />'
                        if output_format == 'xml'
                        else f"- {sym['id']} ({sym['file']}:{sym.get('start_line', 0)})\n"
                    )
                    compact_cost = self.token_counter.count(compact_block)
                    if used + compact_cost <= budget:
                        used_blocks.append(compact_block)
                        used += compact_cost
                        included_ids.add(sym['id'])
                    else:
                        omitted += 1
            if section_close:
                used_blocks.append(section_close)

        plan_blocks: List[str] = []
        expansion_plan = self._precision_expansion_plan(
            selected,
            full_code_ids,
            included_ids,
            max_items=int(budget_settings['expansion_items']),
        )
        if expansion_plan:
            if output_format == 'xml':
                plan_blocks.append('  <expansion-plan>')
                for item in expansion_plan:
                    plan_blocks.append(
                        f'    <expand symbol="{xml_escape(item["symbol"])}" tier="{xml_escape(item["tier"])}" '
                        f'reason="{xml_escape(item["reason"])}" tool="{xml_escape(item["expand_with"])}" />'
                    )
                plan_blocks.append('  </expansion-plan>')
            else:
                plan_blocks.append("\n## NEXT EXPANSIONS")
                for item in expansion_plan:
                    plan_blocks.append(
                        f'- {item["symbol"]} [{item["tier"]}] via `{item["expand_with"]}`'
                    )
            while plan_blocks and used + self.token_counter.count("\n".join(plan_blocks)) > budget:
                if len(plan_blocks) <= 2:
                    plan_blocks = []
                    break
                plan_blocks.pop(-2 if output_format == 'xml' else -1)
            if plan_blocks:
                used_blocks.extend(plan_blocks)

        if output_format == 'xml':
            output = header + "\n".join(used_blocks)
            if omitted:
                output += f'\n  <omitted_symbols count="{omitted}" />'
            output += "\n" + footer
        else:
            output = header + "\n".join(used_blocks)
            if omitted:
                output += f"\n\nOmitted symbols: {omitted}\n"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[+] Precision context: {output_path} | {self.token_counter.count(output)} tokens")

# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description='ARGON v9.0 // UNIVERSAL_SCANNER')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--context', action='store_true', help='Generar ARGON.md y argon_graph.json')
    parser.add_argument('--precision', action='store_true', help='Modo precision: tokens reales, .gitignore, imports resueltos, PageRank y contexto semántico')
    parser.add_argument('--task', default='', help='Tarea para seleccionar contexto precision')
    parser.add_argument('--model', default='gpt-4.1', help='Modelo para conteo real de tokens en precision')
    parser.add_argument('--format', choices=['xml', 'json', 'markdown'], default='xml', help='Formato de salida precision')
    parser.add_argument('--view', action='store_true', help='Generar argon_view.html usando argon_template.html')
    parser.add_argument('--open-view', action='store_true', help='Abrir argon_view.html tras generarlo')
    parser.add_argument('--budget', type=int, default=4096, help='Token budget para ARGON.md (default: 4096)')
    parser.add_argument(
        '--budget-profile',
        choices=sorted(PRECISION_BUDGET_PROFILES),
        default='custom',
        help='Perfil Precision opcional: micro=1500, standard=4096, deep=8192, custom=usa --budget',
    )
    parser.add_argument('--compact', action='store_true', help='JSON compacto (sin symbols detallados)')
    parser.add_argument('--output', default=None, metavar='DIR',
                        help='Directorio de salida para ARGON.md y argon_graph.json '
                             '(default: raíz del proyecto escaneado)')
    args = parser.parse_args()

    target = os.path.abspath(args.path)
    # Output dir: --output flag > proyecto escaneado > cwd (legacy fallback)
    if args.output:
        output_dir = os.path.abspath(args.output)
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = target  # junto al proyecto (Opción A)
    try:
        engine = ArgonEngine(target, precision=args.precision, model=args.model, output_dir=output_dir if args.output else '')
    except RuntimeError as e:
        print(f"[!] {e}")
        return

    if args.context or args.precision:
        graph = engine.build_graph()

        if args.compact:
            for n in graph['nodes']:
                n['symbol_count'] = len(n.get('symbols', []))
                n['symbols'] = []
                if n.get('summary') and len(n['summary']) > 60:
                    n['summary'] = n['summary'][:60] + '...'

        if args.precision:
            task = args.task or "general repository understanding"
            ext = {'xml': 'xml', 'json': 'json', 'markdown': 'md'}[args.format]
            engine.generate_precision_context(
                graph,
                os.path.join(output_dir, f'ARGON_PRECISION.{ext}'),
                task=task,
                max_tokens=args.budget,
                output_format=args.format,
                budget_profile=args.budget_profile,
            )
        else:
            engine.generate_context_report(graph, os.path.join(output_dir, 'ARGON.md'), max_tokens=args.budget)

        graph_path = os.path.join(output_dir, 'argon_graph.json')
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        if args.view or args.open_view:
            try:
                from argon_view import ArgonVisualizer
                template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'argon_template.html')
                view_path = os.path.join(output_dir, 'argon_view.html')
                ArgonVisualizer(graph_path, template_path).render(view_path, open_browser=args.open_view)
            except Exception as e:
                print(f"[!] No se pudo generar argon_view.html: {e}")

        s = graph['stats']
        print(f"[+] Mapeados {s['total_files']} archivos, {s['total_connections']} conexiones.")
    else:
        print("[!] Usa --context o --precision para generar el mapa del proyecto.")
        print("    Ejemplo: python argon.py . --context")
        print("    Precision: python argon.py . --precision --task \"fix auth bug\" --budget 4096 --format xml --view")
        print("    Opciones: --budget 8192 --compact")


if __name__ == '__main__':
    main()
