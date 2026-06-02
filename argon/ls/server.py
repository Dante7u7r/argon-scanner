"""ARGON Language Server Protocol implementation for IDE integration."""

import json
import os
import sys
from typing import Any, Dict, List, Optional


class LSPServer:
    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self._graph = None
        self._engine = None
        self._initialized = False

    def _ensure_engine(self) -> None:
        if self._engine is None:
            from argon.engine.graph import ArgonEngine
            self._engine = ArgonEngine(self.root, precision=True)
            self._graph = self._engine.build_graph()

    def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._initialized = True
        return {
            'capabilities': {
                'textDocumentSync': 1,
                'definitionProvider': True,
                'referencesProvider': True,
                'workspaceSymbolProvider': True,
                'hoverProvider': True,
            }
        }

    def handle_definition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_engine()
        text_document = params.get('textDocument', {})
        uri = text_document.get('uri', '')
        file_path = uri.replace('file://', '') if uri.startswith('file://') else uri
        position = params.get('position', {})
        line = position.get('line', 0) + 1

        file_rel = os.path.relpath(file_path, self.root).replace('\\', '/')
        for sym in self._graph.get('symbols', []):
            if sym.get('file') == file_rel and sym.get('start_line') == line:
                return {
                    'uri': f"file://{os.path.join(self.root, sym.get('file', ''))}",
                    'range': {
                        'start': {'line': sym.get('start_line', 1) - 1, 'character': 0},
                        'end': {'line': sym.get('end_line', sym.get('start_line', 1)) - 1, 'character': 0},
                    }
                }
        return {'uri': '', 'range': {'start': {'line': 0, 'character': 0}, 'end': {'line': 0, 'character': 0}}}

    def handle_references(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._ensure_engine()
        text_document = params.get('textDocument', {})
        uri = text_document.get('uri', '')
        file_path = uri.replace('file://', '') if uri.startswith('file://') else uri
        position = params.get('position', {})
        line = position.get('line', 0) + 1

        file_rel = os.path.relpath(file_path, self.root).replace('\\', '/')
        symbol_id = None
        for sym in self._graph.get('symbols', []):
            if sym.get('file') == file_rel and sym.get('start_line') == line:
                symbol_id = sym.get('id', '')
                break

        if not symbol_id:
            return []

        references = []
        for edge in self._graph.get('edges', []):
            if edge.get('target') == symbol_id:
                source_id = edge.get('source', '')
                for sym in self._graph.get('symbols', []):
                    if sym.get('id') == source_id:
                        references.append({
                            'uri': f"file://{os.path.join(self.root, sym.get('file', ''))}",
                            'range': {
                                'start': {'line': sym.get('start_line', 1) - 1, 'character': 0},
                                'end': {'line': sym.get('end_line', sym.get('start_line', 1)) - 1, 'character': 0},
                            }
                        })
                        break
        return references

    def handle_workspace_symbol(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._ensure_engine()
        query = params.get('query', '').lower()
        if not query:
            return []

        results = []
        for sym in self._graph.get('symbols', []):
            name = sym.get('name', '').lower()
            if query in name:
                results.append({
                    'name': sym.get('name', ''),
                    'kind': self._symbol_kind_to_lsp(sym.get('kind', '')),
                    'location': {
                        'uri': f"file://{os.path.join(self.root, sym.get('file', ''))}",
                        'range': {
                            'start': {'line': sym.get('start_line', 1) - 1, 'character': 0},
                            'end': {'line': sym.get('end_line', sym.get('start_line', 1)) - 1, 'character': 0},
                        }
                    }
                })
                if len(results) >= 50:
                    break
        return results

    def handle_hover(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_engine()
        text_document = params.get('textDocument', {})
        uri = text_document.get('uri', '')
        file_path = uri.replace('file://', '') if uri.startswith('file://') else uri
        position = params.get('position', {})
        line = position.get('line', 0) + 1

        file_rel = os.path.relpath(file_path, self.root).replace('\\', '/')
        for sym in self._graph.get('symbols', []):
            if sym.get('file') == file_rel and sym.get('start_line') == line:
                content = f"**{sym.get('name', '')}** ({sym.get('kind', '')})\n\n"
                if sym.get('signature'):
                    content += f"```python\n{sym.get('signature')}\n```\n\n"
                content += f"File: `{sym.get('file', '')}:{sym.get('start_line', 0)}`"
                return {
                    'contents': {
                        'kind': 'markdown',
                        'value': content
                    }
                }
        return {'contents': {'kind': 'markdown', 'value': ''}}

    def _symbol_kind_to_lsp(self, kind: str) -> int:
        kind_map = {
            'func': 12, 'function': 12,
            'class': 5,
            'interface': 11,
            'enum': 10,
            'struct': 23,
            'variable': 13,
            'constant': 14,
        }
        return kind_map.get(kind.lower(), 12)

    def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        if method == 'initialize':
            return self.handle_initialize(params)
        elif method == 'textDocument/definition':
            return self.handle_definition(params)
        elif method == 'textDocument/references':
            return self.handle_references(params)
        elif method == 'workspace/symbol':
            return self.handle_workspace_symbol(params)
        elif method == 'textDocument/hover':
            return self.handle_hover(params)
        return None

    def run_stdio(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                if line.startswith('Content-Length:'):
                    length = int(line.split(':')[1].strip())
                    sys.stdin.readline()
                    body = sys.stdin.read(length)
                    message = json.loads(body)

                    msg_id = message.get('id')
                    method = message.get('method', '')
                    params = message.get('params', {})

                    response = self.handle_request(method, params)

                    if msg_id is not None:
                        reply = {
                            'jsonrpc': '2.0',
                            'id': msg_id,
                            'result': response,
                        }
                        reply_str = json.dumps(reply)
                        sys.stdout.write(f"Content-Length: {len(reply_str)}\r\n\r\n{reply_str}")
                        sys.stdout.flush()
            except Exception as e:
                error_reply = {
                    'jsonrpc': '2.0',
                    'id': msg_id if 'msg_id' in dir() else None,
                    'error': {'code': -32603, 'message': str(e)},
                }
                reply_str = json.dumps(error_reply)
                sys.stdout.write(f"Content-Length: {len(reply_str)}\r\n\r\n{reply_str}")
                sys.stdout.flush()
