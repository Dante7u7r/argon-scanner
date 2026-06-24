from typing import Any, Dict, List, Optional, Set, Tuple

from argon.models import Symbol

TS_LANG_MAP = {
    'py': 'python', 'js': 'javascript', 'jsx': 'javascript',
    'ts': 'typescript', 'tsx': 'tsx', 'vue': 'typescript',
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


class TreeSitterAdapter:
    @staticmethod
    def parse(parser, content: str):
        try:
            return parser.parse(content)
        except Exception:
            return parser.parse(content.encode('utf-8', errors='replace'))

    @staticmethod
    def get_root(tree) -> Any:
        rn = tree.root_node
        if callable(rn):
            return rn()
        return rn

    @staticmethod
    def get_children(node):
        """Get children as list, works with both old and new API."""
        if hasattr(node, 'children') and not callable(node.children):
            return list(node.children)
        # New API: use child() and child_count()
        count = node.child_count() if callable(node.child_count) else node.child_count
        return [node.child(i) for i in range(count)]

    @staticmethod
    def get_type(node) -> str:
        """Get node type/kind, works with both old and new API."""
        if hasattr(node, 'type') and not callable(node.type):
            return node.type
        kind = node.kind() if callable(node.kind) else node.kind
        return kind

    @staticmethod
    def get_start_point(node):
        """Get start point (row, col), works with both old and new API."""
        if hasattr(node, 'start_point') and not callable(node.start_point):
            return node.start_point
        pos = node.start_position if not callable(node.start_position) else node.start_position()
        return (pos.row, pos.column)

    @staticmethod
    def get_end_point(node):
        """Get end point (row, col), works with both old and new API."""
        if hasattr(node, 'end_point') and not callable(node.end_point):
            return node.end_point
        pos = node.end_position if not callable(node.end_position) else node.end_position()
        return (pos.row, pos.column)

    @staticmethod
    def get_start_byte(node):
        """Get start byte offset, works with both old and new API."""
        if hasattr(node, 'start_byte') and not callable(node.start_byte):
            return node.start_byte
        return node.start_byte()

    @staticmethod
    def get_end_byte(node):
        """Get end byte offset, works with both old and new API."""
        if hasattr(node, 'end_byte') and not callable(node.end_byte):
            return node.end_byte
        return node.end_byte()

    @staticmethod
    def decode_text(node, source: str = None) -> str:
        """Extract text from node using byte offsets.
        
        If source is provided, uses byte offsets from node.
        If source is not provided, falls back to checking node.text attribute/method
        (for backward compatibility with tests).
        """
        # New API: use byte offsets from source
        if source is not None:
            start = TreeSitterAdapter.get_start_byte(node)
            end = TreeSitterAdapter.get_end_byte(node)
            if start is not None and end is not None and start < end:
                try:
                    return source[start:end]
                except Exception:
                    pass
        
        # Backward compatibility: try to get text from node directly
        # New API: text is a method
        text = None
        if callable(getattr(node, 'text', None)):
            try:
                text = node.text()
            except Exception:
                pass
        if text is None:
            text = getattr(node, 'text', None)
        if text is None:
            return ""
        if isinstance(text, bytes):
            return text.decode('utf-8', errors='replace')
        return str(text)


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

    def _find_name(self, node, source: str) -> Optional[str]:
        for child in TreeSitterAdapter.get_children(node):
            child_type = TreeSitterAdapter.get_type(child)
            if child_type in ('identifier', 'name', 'type_identifier', 'property_identifier'):
                return TreeSitterAdapter.decode_text(child, source)
        for child in TreeSitterAdapter.get_children(node):
            child_type = TreeSitterAdapter.get_type(child)
            if 'declarator' in child_type:
                return self._find_name(child, source)
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

            import re
            symbol_lines = lines[start_line - 1 : end_line]
            symbol_body = "\n".join(symbol_lines)

            body_call_names = set(re.findall(r'\b([A-Za-z_]\w*)\s*\(', symbol_body))
            body_qualified_calls = set(
                re.findall(r'\b([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*(?:\.|::)\s*([A-Za-z_]\w*)\s*\(', symbol_body)
            )
            body_new_calls = set(
                re.findall(r'\bnew\s+([A-Za-z_]\w*)\s*\(', symbol_body)
            )

            calls_list = list(body_call_names)
            for qual, member in body_qualified_calls:
                calls_list.append(f"{qual}.{member}")
            for constructor in body_new_calls:
                calls_list.append(constructor)

            symbols.append(Symbol(
                name=name,
                kind=self._kind_from_pack(getattr(item, 'kind', None)),
                line=start_line,
                end_line=end_line,
                signature=signature or "",
                exported=exported,
                calls=calls_list,
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
            tree = TreeSitterAdapter.parse(parser, content)

            symbol_map = TS_SYMBOL_NODES.get(lang, TS_DEFAULT_SYMBOLS)
            symbols = []
            seen = set()

            def collect_calls(n, calls_list, is_root=False):
                node_type = TreeSitterAdapter.get_type(n)
                if not is_root and node_type in symbol_map:
                    return
                is_call = ('call' in node_type or
                           'invocation' in node_type or
                           'new_expression' in node_type or
                           'object_creation' in node_type)
                if is_call:
                    children = TreeSitterAdapter.get_children(n)
                    if children:
                        callee = children[0]
                        if TreeSitterAdapter.decode_text(callee, content) == 'new' and len(children) > 1:
                            callee = children[1]
                        callee_text = TreeSitterAdapter.decode_text(callee, content).strip()
                        if callee_text:
                            calls_list.append(callee_text)
                for child in TreeSitterAdapter.get_children(n):
                    collect_calls(child, calls_list, is_root=False)

            def walk(node):
                node_type = TreeSitterAdapter.get_type(node)
                if node_type in symbol_map:
                    name = self._find_name(node, content)
                    if name and name not in seen and len(name) > 1:
                        start_point = TreeSitterAdapter.get_start_point(node)
                        end_point = TreeSitterAdapter.get_end_point(node)
                        start_line = start_point[0] + 1
                        calls_list = []
                        collect_calls(node, calls_list, is_root=True)
                        symbols.append(Symbol(
                            name=name,
                            kind=symbol_map[node_type],
                            line=start_line,
                            end_line=end_point[0] + 1,
                            signature=self._signature(content, start_line),
                            exported=self._is_exported(content, start_line),
                            calls=calls_list,
                        ))
                        seen.add(name)
                for child in TreeSitterAdapter.get_children(node):
                    walk(child)

            root = TreeSitterAdapter.get_root(tree)
            walk(root)
            return symbols
        except Exception:
            return self._extract_with_process(content, lang)
