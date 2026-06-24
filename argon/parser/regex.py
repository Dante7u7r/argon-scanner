import re
from typing import Any, Dict, List, Optional, Set, Tuple

from argon.models import Symbol
from argon.utils.noise import _COMMENT_PATS, _DOCSTRING_PATS, _KW_BLACKLIST, IMPORT_EXTS, STDLIB_NOISE

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
_RE_FROM_IMPORT = re.compile(
    r'\bfrom\s+["\']([\w./@\-]+)["\']'
)
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
_RE_MULTI_JS = re.compile(r'^\s*(?:import|export)\s*\{')
_RE_MULTI_PY = re.compile(r'^\s*from\s+[\w.]+\s+import\s*\(')
_RE_MULTI_RUST = re.compile(r'^\s*use\s+\S+::\{')
_RE_PHP_USE = re.compile(r'^\s*use\s+(?P<name>[A-Za-z_][\w\\]*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?\s*;')
_RE_PHP_NAMESPACE = re.compile(r'^\s*namespace\s+(?P<name>[A-Za-z_][\w\\]*)\s*;')
_RE_RUST_USE = re.compile(r'^\s*use\s+(?P<full>(?:crate|super|self)(?:::[\w*]+)*)(?:::\{[^}]*\}|\s*\{[^}]*\}|\s*;)')
_RE_RUST_USE_EXTERN = re.compile(r'^\s*use\s+(?P<full>[a-z_]\w*(?:::[\w*]+)*)(?:::\{[^}]*\}|\s*\{[^}]*\}|\s*;)')


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
        m = _RE_CLASS.search(line)
        if m:
            name = m.group(1)
            if name not in seen:
                symbols.append(Symbol(name=name, kind='class', line=i))
                seen.add(name)

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
            for pat in (_RE_IMPORT, _RE_FROM_IMPORT, _RE_REQUIRE):
                for m in pat.finditer(line):
                    imp = m.group(1).strip().strip('"\'')
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


def _accumulate_import_block(lines: List[str], idx: int) -> Optional[Tuple[str, int]]:
    """If line at idx starts a multiline import/export, accumulate until closing paren/brace.

    Returns (joined_block, end_index) or None.
    """
    line = lines[idx]

    if _RE_MULTI_JS.match(line) and '}' not in lines[idx]:
        parts = [line.rstrip('\n\r')]
        for j in range(idx + 1, len(lines)):
            parts.append(lines[j].rstrip('\n\r'))
            if '}' in lines[j]:
                return ' '.join(parts), j
        return None

    if _RE_MULTI_PY.match(lines[idx]):
        parts = [line.rstrip('\n\r')]
        for j in range(idx + 1, len(lines)):
            parts.append(lines[j].rstrip('\n\r'))
            if lines[j].strip() == ')':
                block = ' '.join(parts)
                block = re.sub(r'import\s*\(\s*', 'import ', block, count=1)
                block = re.sub(r'\s*\)\s*$', '', block)
                return block, j
        return None

    if _RE_MULTI_RUST.match(line) and '}' not in lines[idx]:
        parts = [line.rstrip('\n\r')]
        for j in range(idx + 1, len(lines)):
            parts.append(lines[j].rstrip('\n\r'))
            if '}' in lines[j]:
                return ' '.join(parts), j
        return None

    return None


def _extract_import_records(lines: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    exports: List[str] = []
    in_template = False
    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1
        skip_import_scan = in_template
        if _has_unescaped_backtick(line):
            in_template = not in_template
        if skip_import_scan:
            i += 1
            continue

        # Multiline accumulation for import/export constructs
        acc = _accumulate_import_block(lines, i)
        if acc:
            line, end_idx = acc
        else:
            end_idx = i

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
                'line': line_num,
                'names': names,
                'specifiers': specifiers,
                'kind': 'import',
            })
            i = end_idx + 1
            continue
        m = _RE_IMPORT_SIDE_EFFECT.match(line)
        if m:
            records.append({'source': m.group('source'), 'line': line_num, 'names': [], 'kind': 'import'})
            i = end_idx + 1
            continue
        m = _RE_REQUIRE.search(line)
        if m:
            records.append({'source': m.group(1), 'line': line_num, 'names': [], 'kind': 'require'})
            i = end_idx + 1
            continue
        m = _RE_PY_FROM_IMPORT.match(line)
        if m:
            names = [name.strip() for name in m.group('named').split(',') if name.strip()]
            records.append({
                'source': m.group('source'),
                'line': line_num,
                'names': names,
                'specifiers': [{'imported': name, 'local': name} for name in names],
                'kind': 'import',
            })
            i = end_idx + 1
            continue
        m = _RE_EXPORT_FROM.match(line)
        if m:
            names = ['*'] if m.group('body') == '*' else _split_named_imports(m.group('body').strip('{}'))
            specifiers = [{'imported': '*', 'local': '*'}] if names == ['*'] else _split_named_specifiers(m.group('body').strip('{}'))
            records.append({'source': m.group('source'), 'line': line_num, 'names': names, 'specifiers': specifiers, 'kind': 're-export'})
            exports.extend(names)
            i = end_idx + 1
            continue
        m = _RE_EXPORT_DECL.match(line)
        if m:
            exports.append(m.group('name'))
            if line.strip().startswith('export default'):
                exports.append('default')
            i = end_idx + 1
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
                'line': line_num,
                'names': [local],
                'specifiers': [{'imported': local, 'local': local}],
                'kind': 'php-use',
            })
            i = end_idx + 1
            continue
        m = _RE_RUST_USE.match(line)
        if m:
            full_path = m.group('full')
            brace_match = re.search(r'\{([^}]*)\}', line)
            if brace_match:
                items_str = brace_match.group(1).strip()
                if '*' in items_str.split(','):
                    names = ['*']
                    specifiers = [{'imported': '*', 'local': '*'}]
                else:
                    imported_items = re.findall(r'(\w+)(?:\s+as\s+(\w+))?', items_str)
                    names = [n[0] for n in imported_items if n[0]]
                    specifiers = [{'imported': n[0], 'local': n[1] or n[0]} for n in imported_items if n[0]]
            else:
                last_part = full_path.split('::')[-1]
                names = [last_part]
                specifiers = [{'imported': last_part, 'local': last_part}]
            records.append({
                'source': full_path,
                'line': line_num,
                'names': names,
                'specifiers': specifiers,
                'kind': 'rust-use',
            })
            i = end_idx + 1
            continue
        m = _RE_RUST_USE_EXTERN.match(line)
        if m:
            full_path = m.group('full')
            brace_match = re.search(r'\{([^}]*)\}', line)
            if brace_match:
                items_str = brace_match.group(1).strip()
                if '*' in items_str.split(','):
                    names = ['*']
                    specifiers = [{'imported': '*', 'local': '*'}]
                else:
                    imported_items = re.findall(r'(\w+)(?:\s+as\s+(\w+))?', items_str)
                    names = [n[0] for n in imported_items if n[0]]
                    specifiers = [{'imported': n[0], 'local': n[1] or n[0]} for n in imported_items if n[0]]
            else:
                last_part = full_path.split('::')[-1]
                names = [last_part]
                specifiers = [{'imported': last_part, 'local': last_part}]
            records.append({
                'source': full_path,
                'line': line_num,
                'names': names,
                'specifiers': specifiers,
                'kind': 'rust-use',
            })
            i = end_idx + 1
            continue
        i = end_idx + 1
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
