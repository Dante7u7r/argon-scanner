from typing import Any

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

# ============================================================
# TODO: Deuda técnica — tree_sitter_language_pack v1.9.1
# ============================================================
# Limitación actual:
#   tree_sitter_language_pack v1.9.1 expone un objeto Language
#   nativo (Rust vía PyO3) que NO tiene método .query(). El
#   tree_sitter.Query de la librería tree_sitter 0.25.2 requiere
#   un tree_sitter.Language nativo, incompatible ABI con el
#   builtins.Language del pack. Intentar mezclarlos causa SEGFAULT.
#
# Solución implementada:
#   Los strings .scm en CALL_QUERIES definen los patrones de
#   llamada por lenguaje. El matching se implementa mediante
#   child_by_field_name() sobre el AST parseado por el pack,
#   emulando la semántica de las queries S-expression.
#
# Plan de migración futuro:
#   Cuando tree_sitter_language_pack exponga .query() nativo
#   (o sea compatible con tree_sitter.Query), reemplazar
#   _collect_calls_in_node() y _extract_callee_from_call()
#   con ejecución directa de los strings .scm. La migración
#   sería casi drop-in porque CALL_QUERIES ya contiene las
#   queries correctas y captura los mismos @callee/@method.
#   Esto daría un salto en rendimiento (O(pattern) vs O(node))
#   y eliminaría el código de walk manual.
# ============================================================

CALL_QUERIES = {
    'python': {
        'call': '(call function: (identifier) @callee)',
        'method_call': (
            '(call function: (attribute attribute: (identifier) @method)'
            ' object: (identifier) @object)'
        ),
    },
    'javascript': {
        'call': '(call_expression function: (identifier) @callee)',
        'method_call': (
            '(call_expression function: (member_expression'
            ' property: (property_identifier) @method)'
            ' object: (identifier) @object)'
        ),
        'new_expression': '(new_expression constructor: (identifier) @constructor)',
    },
    'typescript': {
        'call': '(call_expression function: (identifier) @callee)',
        'method_call': (
            '(call_expression function: (member_expression'
            ' property: (property_identifier) @method)'
            ' object: (identifier) @object)'
        ),
        'new_expression': '(new_expression constructor: (identifier) @constructor)',
    },
    'tsx': {
        'call': '(call_expression function: (identifier) @callee)',
        'method_call': (
            '(call_expression function: (member_expression'
            ' property: (property_identifier) @method)'
            ' object: (identifier) @object)'
        ),
        'new_expression': '(new_expression constructor: (identifier) @constructor)',
    },
    'rust': {
        'call': '(call_expression function: (identifier) @callee)',
        'method_call': (
            '(call_expression function: (field_expression'
            ' field: (field_identifier) @method)'
            ' value: (identifier) @object)'
        ),
    },
    'go': {
        'call': '(call_expression function: (identifier) @callee)',
    },
    'java': {
        'call': '(method_invocation name: (identifier) @callee)',
        'method_call': (
            '(method_invocation name: (identifier) @callee'
            ' object: (expression) @object)'
        ),
    },
    'c_sharp': {
        'call': '(invocation_expression expression: (identifier) @callee)',
        'method_call': (
            '(invocation_expression expression:'
            ' (member_access_expression name: (identifier) @method) @object)'
        ),
    },
    'cpp': {
        'call': '(call_expression function: (identifier) @callee)',
        'method_call': (
            '(call_expression function: (field_expression'
            ' field: (field_identifier) @method) @object)'
        ),
    },
    'c': {
        'call': '(call_expression function: (identifier) @callee)',
    },
}

CALL_NODE_TYPES = {
    'python': {'call'},
    'javascript': {'call_expression', 'new_expression'},
    'typescript': {'call_expression', 'new_expression'},
    'tsx': {'call_expression', 'new_expression'},
    'rust': {'call_expression'},
    'go': {'call_expression'},
    'java': {'method_invocation'},
    'c_sharp': {'invocation_expression'},
    'cpp': {'call_expression'},
    'c': {'call_expression'},
    'ruby': {'call'},
    'php': {'function_call_expression', 'method_call_expression'},
    'swift': {'function_call_expression', 'method_call_expression'},
    'kotlin': {'call_expression'},
    'scala': {'call_expression'},
    'lua': {'function_call'},
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

    @staticmethod
    def get_child_by_field_name(node, name: str):
        """Get child by field name, works with both old and new API."""
        if hasattr(node, 'child_by_field_name'):
            try:
                return node.child_by_field_name(name)
            except Exception:
                pass
        # Fallback: find child with matching field name via walk
        for child in TreeSitterAdapter.get_children(node):
            if hasattr(child, 'field_name'):
                try:
                    fn = child.field_name()
                    if fn == name:
                        return child
                except Exception:
                    pass
        return None


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

    def _find_name(self, node, source: str) -> str | None:
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

    def _extract_with_process(self, content: str, lang: str) -> list[Symbol]:
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

        symbols: list[Symbol] = []
        seen: set[tuple[str, int]] = set()

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

        def walk_structure(items: list[Any]) -> None:
            for item in items:
                add_item(item)
                walk_structure(getattr(item, 'children', []) or [])

        walk_structure(getattr(result, 'structure', []) or [])
        for item in getattr(result, 'symbols', []) or []:
            add_item(item)
        return symbols

    def _collect_calls_in_node(self, node, content: str, lang: str) -> list[str]:
        """Collect all function calls within a node using field-name matching."""
        calls = []
        default_calls = {'call', 'call_expression', 'new_expression',
                         'invocation', 'object_creation'}
        call_types = CALL_NODE_TYPES.get(lang, default_calls)
        children = TreeSitterAdapter.get_children(node)

        for child in children:
            child_type = TreeSitterAdapter.get_type(child)

            if child_type in call_types:
                callee_text = self._extract_callee_from_call(child, content, lang)
                if callee_text:
                    calls.append(callee_text)
                # Still recurse into call's children (e.g., arguments) to find nested calls
                # but avoid double-counting by not recursing into 'function' child
                for grandchild in TreeSitterAdapter.get_children(child):
                    grandchild_type = TreeSitterAdapter.get_type(grandchild)
                    if grandchild_type in ('arguments', 'argument_list'):
                        calls.extend(self._collect_calls_in_node(grandchild, content, lang))
                continue

            # Recurse into non-call children
            if child_type not in TS_SYMBOL_NODES.get(lang, TS_DEFAULT_SYMBOLS):
                calls.extend(self._collect_calls_in_node(child, content, lang))

        return calls

    def _extract_callee_from_call(self, call_node, content: str, lang: str) -> str | None:
        """Extract callee name from a call node using field-name matching."""
        fn_node = TreeSitterAdapter.get_child_by_field_name(call_node, 'function')
        if not fn_node:
            fn_node = TreeSitterAdapter.get_child_by_field_name(call_node, 'constructor')
        if not fn_node:
            fn_node = TreeSitterAdapter.get_child_by_field_name(call_node, 'name')

        if not fn_node:
            return None

        fn_type = TreeSitterAdapter.get_type(fn_node)

        if fn_type in ('identifier', 'type_identifier', 'property_identifier'):
            return TreeSitterAdapter.decode_text(fn_node, content)

        if fn_type == 'attribute':
            # Python: obj.method
            obj = TreeSitterAdapter.get_child_by_field_name(fn_node, 'object')
            attr = TreeSitterAdapter.get_child_by_field_name(fn_node, 'attribute')
            if obj and attr:
                obj_text = TreeSitterAdapter.decode_text(obj, content)
                attr_text = TreeSitterAdapter.decode_text(attr, content)
                return f"{obj_text}.{attr_text}"

        if fn_type == 'member_expression':
            # TypeScript/JS: obj.method
            obj = TreeSitterAdapter.get_child_by_field_name(fn_node, 'object')
            prop = TreeSitterAdapter.get_child_by_field_name(fn_node, 'property')
            if obj and prop:
                obj_text = TreeSitterAdapter.decode_text(obj, content)
                prop_text = TreeSitterAdapter.decode_text(prop, content)
                return f"{obj_text}.{prop_text}"

        if fn_type == 'field_expression':
            # Rust: obj.method
            val = TreeSitterAdapter.get_child_by_field_name(fn_node, 'value')
            field = TreeSitterAdapter.get_child_by_field_name(fn_node, 'field')
            if val and field:
                val_text = TreeSitterAdapter.decode_text(val, content)
                field_text = TreeSitterAdapter.decode_text(field, content)
                return f"{val_text}.{field_text}"

        if fn_type == 'call_expression':
            # Nested call: get the inner function
            inner_fn = TreeSitterAdapter.get_child_by_field_name(fn_node, 'function')
            if inner_fn:
                return self._extract_callee_from_call(fn_node, content, lang)

        return TreeSitterAdapter.decode_text(fn_node, content)

    def extract(self, content: str, ext: str) -> list[Symbol]:
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
            scope_stack: list[str] = []

            def walk(node, scope_stack: list[str]):
                node_type = TreeSitterAdapter.get_type(node)

                if node_type in symbol_map:
                    name = self._find_name(node, content)
                    if name and name not in seen and len(name) > 1:
                        start_point = TreeSitterAdapter.get_start_point(node)
                        end_point = TreeSitterAdapter.get_end_point(node)
                        start_line = start_point[0] + 1

                        # Collect calls within this symbol's body
                        calls_list = self._collect_calls_in_node(node, content, lang)

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

                        # Push this symbol as new scope for nested calls
                        scope_stack.append(name)
                        for child in TreeSitterAdapter.get_children(node):
                            walk(child, scope_stack)
                        scope_stack.pop()
                        return

                for child in TreeSitterAdapter.get_children(node):
                    walk(child, scope_stack)

            root = TreeSitterAdapter.get_root(tree)
            walk(root, scope_stack)
            return symbols
        except Exception:
            return self._extract_with_process(content, lang)
