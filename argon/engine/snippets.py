"""Snippet extraction and truncation for symbol code blocks."""

import os
from typing import Any, Dict, List


def truncate_snippet(snippet: str, max_tokens: int) -> str:
    tokens = snippet.split()
    if len(tokens) <= max_tokens:
        return snippet
    truncated = " ".join(tokens[:max_tokens])
    last_nl = truncated.rfind("\n")
    if last_nl > max_tokens // 2:
        truncated = truncated[:last_nl]
    return truncated + "\n    ..."


def read_symbol_snippet(root: str, parser, symbol: Dict[str, Any], max_lines: int = 80) -> str:
    path = os.path.join(root, symbol['file'])
    content = parser.safe_read(path)
    if not content:
        return ""
    lines = content.splitlines()
    start = max(1, int(symbol.get('start_line') or 1))
    end = max(start, int(symbol.get('end_line') or start))
    if end - start + 1 > max_lines:
        end = start + max_lines - 1
    return "\n".join(lines[start - 1:end])


def read_contextual_snippet(root: str, parser, symbol: Dict[str, Any], keywords: List[str], tier: str) -> str:
    path = os.path.join(root, symbol['file'])
    content = parser.safe_read(path)
    if not content:
        return ""
    lines = content.splitlines()
    start = max(1, int(symbol.get('start_line') or 1))
    end = max(start, int(symbol.get('end_line') or start))
    if tier == 'support':
        sig_line = lines[start - 1].strip() if start <= len(lines) else ""
        return sig_line
    if tier == 'workflow':
        best_line = start
        best_score = 0
        for i in range(start - 1, min(end, len(lines))):
            line_lower = lines[i].lower()
            score = sum(1 for kw in keywords if kw in line_lower)
            if score > best_score:
                best_score = score
                best_line = i + 1
        if best_score > 0:
            ctx_start = max(start, best_line - 5)
            ctx_end = min(end, best_line + 15)
            snippet = "\n".join(lines[ctx_start - 1:ctx_end])
            return truncate_snippet(snippet, 80)
        snippet = "\n".join(lines[start - 1:min(start + 15, end)])
        return truncate_snippet(snippet, 80)
    if tier == 'critical':
        snippet = "\n".join(lines[start - 1:end])
        return truncate_snippet(snippet, 120)
    return "\n".join(lines[start - 1:min(end, start + 79)])
