"""Heuristic test-to-source and source-to-test file mapping."""

import re
from typing import List, Optional


def find_test_counterpart(source_path: str) -> Optional[str]:
    """Given source.py, find corresponding test_source.py or similar."""
    parts = source_path.rsplit('/', 1)
    if len(parts) == 2:
        directory, filename = parts
    else:
        directory, filename = '', parts[0]

    name, ext = _splitext(filename)
    patterns = [
        f"{directory}/test_{name}.{ext}",
        f"{directory}/{name}_test.{ext}",
        f"{directory}/{name}.test.{ext}",
        f"{directory}/test/{name}.{ext}",
        f"{directory}/tests/{name}.{ext}",
        f"{directory}/__tests__/{name}.{ext}",
        f"{directory}/spec/{name}.{ext}",
        f"{directory}/{name}_spec.{ext}",
    ]
    return patterns[0]  # primary pattern — caller should check existence

def find_test_counterparts(source_path: str) -> List[str]:
    parts = source_path.rsplit('/', 1)
    if len(parts) == 2:
        directory, filename = parts
    else:
        directory, filename = '', parts[0]
    name, ext = _splitext(filename)

    base_patterns = [
        f"{directory}/test_{name}.{ext}",
        f"{directory}/{name}_test.{ext}",
        f"{directory}/{name}.test.{ext}",
        f"{directory}/test/{name}.{ext}",
        f"{directory}/tests/{name}.{ext}",
        f"{directory}/__tests__/{name}.{ext}",
        f"{directory}/spec/{name}.{ext}",
        f"{directory}/{name}_spec.{ext}",
    ]

    # Patterns in top-level test dirs (strip package directory prefix)
    test_dir_patterns = []
    for test_dir in ('test', 'tests', '__tests__', 'spec'):
        test_dir_patterns.append(f"{test_dir}/test_{name}.{ext}")
        test_dir_patterns.append(f"{test_dir}/{name}_test.{ext}")
        test_dir_patterns.append(f"{test_dir}/{name}.test.{ext}")
        test_dir_patterns.append(f"{test_dir}/{directory}/test_{name}.{ext}")
        test_dir_patterns.append(f"{test_dir}/{directory}/{name}_test.{ext}")
        test_dir_patterns.append(f"{test_dir}/{directory}/{name}.{ext}")

    return base_patterns + test_dir_patterns

def find_source_counterpart(test_path: str) -> Optional[str]:
    parts = test_path.rsplit('/', 1)
    if len(parts) == 2:
        directory, filename = parts
    else:
        directory, filename = '', parts[0]

    name, ext = _splitext(filename)
    name = re.sub(r'^(test[_\-]|spec[_\-])', '', name)
    name = re.sub(r'([_\-](test|spec))$', '', name)
    name = name.lstrip('_')

    sibling = f"{directory}/{name}.{ext}"

    for parent_dir in ('test', 'tests', '__tests__', 'spec'):
        marker = f'/{parent_dir}/'
        if marker in f'/{directory}/':
            actual_dir = directory.replace(marker, '/').strip('/')
            if actual_dir:
                return f"{actual_dir}/{name}.{ext}"
            else:
                return f"{name}.{ext}"

    for parent_dir in ('test', 'tests', '__tests__', 'spec'):
        if directory == parent_dir or directory.startswith(f'{parent_dir}/'):
            rel = directory[len(parent_dir):].lstrip('/')
            if rel:
                return f"{rel}/{name}.{ext}"
            return f"{name}.{ext}"

    return sibling

def _splitext(filename: str):
    idx = filename.rfind('.')
    if idx > 0:
        return filename[:idx], filename[idx + 1:]
    return filename, ''
