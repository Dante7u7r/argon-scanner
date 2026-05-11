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
from collections import defaultdict
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict

# Tree-sitter: optional
_HAS_TREESITTER = False
try:
    from tree_sitter_language_pack import get_language, get_parser as ts_get_parser
    _HAS_TREESITTER = True
except ImportError:
    try:
        from tree_sitter_languages import get_language, get_parser as ts_get_parser
        _HAS_TREESITTER = True
    except ImportError:
        pass

# =========================================================================
# DATA MODELS
# =========================================================================

@dataclass
class Symbol:
    name: str
    kind: str
    line: int
    summary: str = ""

@dataclass
class ProjectNode:
    id: str
    type: str
    lines: int = 0
    size_bytes: int = 0
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    summary: str = ""
    importance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# =========================================================================
# TOKEN ESTIMATION
# =========================================================================

def estimate_tokens(text: str) -> int:
    """~4 chars per token heuristic."""
    return max(1, len(text) // 4)

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

    def extract(self, content: str, ext: str) -> List[Symbol]:
        lang = TS_LANG_MAP.get(ext)
        if not lang:
            return []
        parser = self._get_parser(lang)
        if not parser:
            return []
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
                    symbols.append(Symbol(name=name, kind=symbol_map[node.type], line=node.start_point[0] + 1))
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
_COMMENT_PATS = [
    re.compile(r'^\s*#\s*(.+)'),
    re.compile(r'^\s*//\s*(.+)'),
    re.compile(r'^\s*\*\s*(.+)'),
    re.compile(r'^\s*--\s*(.+)'),
    re.compile(r'^\s*;\s*(.+)'),
]
_DOCSTRING_PATS = [
    re.compile(r'^\s*"""(.+?)"""'),
    re.compile(r"^\s*'''(.+?)'''"),
    re.compile(r'^\s*/\*\*?\s*(.+)'),
]


def _regex_extract(lines: List[str]) -> Tuple[List[Symbol], List[str]]:
    symbols = []
    imports = []
    seen: Set[str] = set()

    for i, line in enumerate(lines, 1):
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
            m = pat.search(line)
            if m:
                name = m.group(1)
                break
        if name and name not in seen and len(name) > 1 and name.lower() not in _KW_BLACKLIST:
            symbols.append(Symbol(name=name, kind='func', line=i))
            seen.add(name)

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
                node.symbols = ts_syms
                _, imports = _regex_extract(lines)
                node.imports = imports
                node.summary = _extract_cortex(lines)
                return node

        # Fallback: regex
        syms, imports = _regex_extract(lines)
        node.symbols = syms
        node.imports = imports
        node.summary = _extract_cortex(lines)
        return node

# =========================================================================
# ENGINE
# =========================================================================

class ArgonEngine:
    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.sql', '.c', '.cpp', '.h', '.hpp',
            '.java', '.go', '.rs', '.php', '.rb', '.cs', '.sh', '.bat', '.ps1',
            '.md', '.json', '.yaml', '.yml', '.toml', '.ini', '.xml', '.html', '.css',
            '.swift', '.kt', '.scala', '.ex', '.exs', '.lua', '.r', '.jl',
        }
        self.skip_dirs = {
            '__pycache__', '.git', 'node_modules', 'venv', '.venv',
            'dist', 'build', '.next', 'target', '.cache', 'coverage',
            '.pytest_cache', 'vendor', 'bin', 'obj', '.idea', '.vs',
        }
        self.skip_files = {
            'argon_graph.json', 'ARGON.md', 'argon_view.html',
            'argon.py', 'argon_mcp.py', 'argon_view.py', 'argon_watch.py',
            'argon_template.html',
        }
        self.parser = UniversalParser(self.root)

    def _should_skip(self, path: str, is_dir: bool) -> bool:
        name = os.path.basename(path)
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
            os.path.splitext(name)[1].lower() not in self.extensions or
            sz > 2_000_000
        )

    def _compute_importance(self, nodes: List[ProjectNode], edges: List[Dict]) -> None:
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
            n.importance = round(c * 0.6 + l * 0.3 + s * 0.1, 4)

    def build_graph(self) -> Dict[str, Any]:
        nodes: List[ProjectNode] = []
        print(f"[*] ARGON v9.0 — Escaneando: {self.root}")
        print(f"[*] Parser: {self.parser.mode.upper()}")

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if not self._should_skip(os.path.join(dirpath, d), True)
            ]
            for f in filenames:
                fpath = os.path.join(dirpath, f)
                if self._should_skip(fpath, False):
                    continue
                nodes.append(self.parser.parse(fpath))

        # === O(N) edge builder with hash index ===
        node_ids = {n.id for n in nodes}
        path_index: Dict[str, Set[str]] = defaultdict(set)
        for nid in node_ids:
            base = nid.rsplit('.', 1)[0]
            path_index[base].add(nid)
            path_index[base.split('/')[-1]].add(nid)

        AMBIGUOUS_NAMES = {'utils', 'helpers', 'config', 'types', 'index', 'main', 'constants', 'common', 'models', 'views'}
        edges = []
        seen_edges: Set[tuple] = set()

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

        return {
            'root': os.path.basename(self.root),
            'nodes': [n.to_dict() for n in nodes],
            'edges': edges,
            'parser_mode': self.parser.mode,
            'stats': {
                'total_files': len(nodes),
                'total_connections': len(edges),
                'timestamp': str(datetime.datetime.now()),
            }
        }

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

# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description='ARGON v9.0 // UNIVERSAL_SCANNER')
    parser.add_argument('path', nargs='?', default='.', help='Ruta del proyecto')
    parser.add_argument('--context', action='store_true', help='Generar ARGON.md y argon_graph.json')
    parser.add_argument('--budget', type=int, default=4096, help='Token budget para ARGON.md (default: 4096)')
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
    engine = ArgonEngine(target)

    if args.context:
        graph = engine.build_graph()

        if args.compact:
            for n in graph['nodes']:
                n['symbol_count'] = len(n.get('symbols', []))
                n['symbols'] = []
                if n.get('summary') and len(n['summary']) > 60:
                    n['summary'] = n['summary'][:60] + '...'

        engine.generate_context_report(graph, os.path.join(output_dir, 'ARGON.md'), max_tokens=args.budget)

        graph_path = os.path.join(output_dir, 'argon_graph.json')
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

        s = graph['stats']
        print(f"[+] Mapeados {s['total_files']} archivos, {s['total_connections']} conexiones.")
    else:
        print("[!] Usa --context para generar el mapa del proyecto.")
        print("    Ejemplo: python argon.py . --context")
        print("    Opciones: --budget 8192 --compact")


if __name__ == '__main__':
    main()
