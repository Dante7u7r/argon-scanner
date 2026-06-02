"""Technical debt marker detection — scan for TODO, FIXME, HACK, and other markers."""

import os
import re
from typing import Any, Dict, List


_MARKER_PATTERN = re.compile(
    r'(?:^|\s)[#/;/*-]*\s*(TODO|FIXME|HACK|XXX|BUG|OPTIMIZE|TEMP|WORKAROUND|KLUDGE|HACKY|CLEANUP|REVISIT)[\s:)]*\s*(.*?)(?:\n|$|(?:--|//|#|;))',
    re.IGNORECASE,
)

_MARKER_SEVERITY = {
    'FIXME': 'high', 'BUG': 'high', 'XXX': 'high',
    'HACK': 'medium', 'HACKY': 'medium', 'KLUDGE': 'medium', 'WORKAROUND': 'medium',
    'TODO': 'low', 'TEMP': 'low', 'OPTIMIZE': 'low', 'CLEANUP': 'low', 'REVISIT': 'low',
}


def scan_file_for_debt(filepath: str, content: str = None) -> List[Dict[str, Any]]:
    markers = []
    if content is None:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            return markers
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for m in _MARKER_PATTERN.finditer(line):
            tag = m.group(1).upper()
            note = m.group(2).strip() if m.group(2) else ''
            markers.append({
                'line': i,
                'tag': tag,
                'severity': _MARKER_SEVERITY.get(tag, 'low'),
                'note': note[:120],
                'text': line.strip()[:200],
            })
    return markers


def scan_project_for_debt(root: str, file_paths: List[str]) -> Dict[str, Any]:
    by_severity: Dict[str, int] = {'high': 0, 'medium': 0, 'low': 0}
    by_tag: Dict[str, int] = {}
    top_files: List[Dict[str, Any]] = []
    total = 0

    for fpath in file_paths:
        abs_path = os.path.join(root, fpath)
        markers = scan_file_for_debt(abs_path)
        if markers:
            file_count = len(markers)
            total += file_count
            top_files.append({
                'file': fpath,
                'count': file_count,
                'top_markers': [
                    {'line': m['line'], 'tag': m['tag'], 'severity': m['severity'], 'note': m['note']}
                    for m in markers[:3]
                ],
            })
            for m in markers:
                by_severity[m['severity']] = by_severity.get(m['severity'], 0) + 1
                by_tag[m['tag']] = by_tag.get(m['tag'], 0) + 1

    top_files.sort(key=lambda x: (
        sum(1 for m in x['top_markers'] if m['severity'] == 'high'),
        x['count'],
    ), reverse=True)

    return {
        'total_markers': total,
        'files_with_markers': len(top_files),
        'by_severity': by_severity,
        'by_tag': dict(by_tag),
        'top_files': top_files[:20],
    }
