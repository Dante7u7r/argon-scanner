from typing import Any, Dict, List, Optional, Set, Tuple

from argon.models import Symbol


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
    def __init__(self, has_tree_sitter: bool = True, has_process: bool = False, ts_pack=None):
        self._parsers = {}
        self._has_tree_sitter = has_tree_sitter
        self._has_process = has_process
        self._ts_pack = ts_pack

    def _get_parser(self, lang: str):
        if lang not in self._parsers:
            try:
                from tree_sitter_language_pack import get_parser as ts_get_parser
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
        if not self._has_process or self._ts_pack is None:
            return []
        try:
            result = self._ts_pack.process(
                content,
                self._ts_pack.ProcessConfig(language=lang, structure=True, imports=False, exports=True, symbols=True),
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
