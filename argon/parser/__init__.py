import os
from typing import List, Optional, Tuple

from argon.models import ProjectNode, Symbol
from argon.parser.regex import (
    IMPORT_EXTS,
    _extract_cortex,
    _extract_import_records,
    _infer_symbol_end_line,
    _regex_extract,
)
from argon.parser.tree_sitter import TS_LANG_MAP, TreeSitterExtractor


class UniversalParser:
    def __init__(self, root: str, has_tree_sitter: bool = False, has_process: bool = False, ts_pack=None):
        self.root = root
        self._ts = TreeSitterExtractor(
            has_tree_sitter=has_tree_sitter,
            has_process=has_process,
            ts_pack=ts_pack,
        ) if has_tree_sitter else None
        self.mode = 'tree-sitter' if has_tree_sitter else 'regex'

    def safe_read(self, filepath: str) -> str:
        for enc in ['utf-8', 'utf-16', 'latin-1', 'cp1252']:
            try:
                with open(filepath, encoding=enc) as f:
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
