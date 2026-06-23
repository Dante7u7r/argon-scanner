"""Snippet extraction and truncation for symbol code blocks."""

import os
import re
from typing import Any, Dict, List

CONTROL_FLOW_KEYWORDS = {
    'if', 'else', 'for', 'while', 'return', 'match', 'switch',
    'case', 'default', 'try', 'catch', 'finally', 'throw', 'raise',
    'yield', 'break', 'continue', 'struct', 'class', 'impl', 'fn',
    'func', 'function', 'pub', 'public', 'private', 'protected'
}

def get_comment_indicator(ext: str) -> str:
    ext = ext.lower().lstrip('.')
    if ext in ('py', 'rb', 'sh', 'toml', 'yaml', 'yml', 'r', 'ex', 'exs'):
        return '#'
    if ext in ('sql',):
        return '--'
    return '//'

def is_control_flow(line: str) -> bool:
    words = re.findall(r'\b[A-Za-z_]\w*\b', line)
    return any(w in CONTROL_FLOW_KEYWORDS for w in words)

def contains_keywords(line: str, keywords: List[str]) -> bool:
    line_lower = line.lower()
    return any(kw.lower() in line_lower for kw in keywords)

def is_call(line: str) -> bool:
    return '(' in line or 'new ' in line or '.' in line or '::' in line

def is_line_active(idx: int, total: int, line: str, keywords: List[str]) -> bool:
    if idx < 2 or idx == total - 1:
        return True
    
    line_stripped = line.strip()
    if not line_stripped:
        return False
        
    if is_control_flow(line_stripped):
        return True
        
    if contains_keywords(line_stripped, keywords):
        return True
        
    if is_call(line_stripped):
        return True
        
    return False

def get_active_mask(lines: List[str], keywords: List[str]) -> List[bool]:
    total = len(lines)
    active = [False] * total
    for i in range(total):
        if is_line_active(i, total, lines[i], keywords):
            active[i] = True
            
    masked = [False] * total
    for i in range(total):
        if active[i]:
            masked[i] = True
            if i > 0:
                masked[i - 1] = True
            if i < total - 1:
                masked[i + 1] = True
                
    return masked

def slice_symbol_body(lines: List[str], keywords: List[str], ext: str) -> str:
    if len(lines) <= 20:
        return "\n".join(lines)
        
    masked = get_active_mask(lines, keywords)
    comment = get_comment_indicator(ext)
    
    output_lines = []
    i = 0
    total = len(lines)
    while i < total:
        if masked[i]:
            output_lines.append(lines[i])
            i += 1
        else:
            start_inactive = i
            while i < total and not masked[i]:
                i += 1
            run_len = i - start_inactive
            if run_len <= 4:
                for j in range(start_inactive, i):
                    output_lines.append(lines[j])
            else:
                first_line = lines[start_inactive]
                indent = first_line[:len(first_line) - len(first_line.lstrip())]
                output_lines.append(f"{indent}{comment} ... [omitted {run_len} lines] ...")
                
    return "\n".join(output_lines)

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
    symbol_lines = lines[start - 1:end]
    ext = os.path.splitext(symbol['file'])[1]
    sliced = slice_symbol_body(symbol_lines, [], ext)
    
    sliced_lines = sliced.splitlines()
    if len(sliced_lines) > max_lines:
        sliced = "\n".join(sliced_lines[:max_lines])
    return sliced


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
        symbol_lines = lines[start - 1:end]
        ext = os.path.splitext(symbol['file'])[1]
        sliced = slice_symbol_body(symbol_lines, keywords, ext)
        return truncate_snippet(sliced, 150)
    return "\n".join(lines[start - 1:min(end, start + 79)])
