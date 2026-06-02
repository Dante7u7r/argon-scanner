"""Testing gap detection — find source files without tests and dead tests."""

from collections import defaultdict
from typing import Any, Dict, List, Set

from argon.engine.testmap import find_test_counterparts, find_source_counterpart


def detect_testing_gaps(all_file_paths: List[str]) -> Dict[str, Any]:
    test_files: Set[str] = set()
    source_files: Set[str] = set()
    source_basenames: Dict[str, str] = {}

    for f in all_file_paths:
        lower = f.lower()
        if _is_test_path(lower):
            test_files.add(f)
        elif f.rsplit('.', 1)[-1] in _SOURCE_EXTS:
            source_files.add(f)
            base = f.rsplit('/', 1)[-1]
            source_basenames.setdefault(base, f)

    tested_sources: Set[str] = set()
    for sf in source_files:
        patterns = find_test_counterparts(sf)
        for p in patterns:
            if p in test_files:
                tested_sources.add(sf)
                break

    # Match test files to sources via basename + counterpart patterns
    test_to_source: Dict[str, str] = {}
    source_from_test: Set[str] = set()
    for tf in test_files:
        src = find_source_counterpart(tf)
        found = None
        if src:
            # Try direct match first
            if src in source_files:
                found = src
            else:
                # Try basename match
                base = src.rsplit('/', 1)[-1]
                found = source_basenames.get(base)

        # Also try basename matching directly from test filename
        if found is None:
            test_base = tf.rsplit('/', 1)[-1]
            for prefix in ('test_', 'spec_'):
                if test_base.startswith(prefix):
                    base = test_base[len(prefix):]
                    found = source_basenames.get(base)
                    break
            if found is None:
                for suffix in ('_test.', '_spec.'):
                    if suffix in test_base:
                        base = test_base[:test_base.index(suffix)] + test_base[test_base.index(suffix) + len(suffix) - 1:]
                        found = source_basenames.get(base)
                        break

        if found and found in source_files:
            test_to_source[tf] = found
            source_from_test.add(found)
            tested_sources.add(found)

    untested = sorted(source_files - tested_sources)
    dead_tests = sorted(tf for tf in test_files if tf not in test_to_source)
    total_source = len(source_files)
    coverage_ratio = round(len(tested_sources) / total_source, 4) if total_source else 0.0

    return {
        'total_source_files': total_source,
        'total_test_files': len(test_files),
        'tested_files': len(tested_sources),
        'coverage_ratio': coverage_ratio,
        'untested_source_files': untested[:50],
        'untested_count': len(untested),
        'dead_test_files': dead_tests[:50],
        'dead_test_count': len(dead_tests),
    }


def _is_test_path(path_lower: str) -> bool:
    base = path_lower.rsplit('/', 1)[-1]
    if base in ('__init__.py', 'conftest.py', 'pytest.ini', 'setup.cfg', 'tox.ini'):
        return False
    for segment in ('/test/', '/tests/', '/__tests__/', '/spec/', '/specs/'):
        if segment in f'/{path_lower}':
            return True
    if path_lower.startswith('test/') or path_lower.startswith('tests/') or path_lower.startswith('spec/'):
        return True
    if base.startswith('test_') or base.endswith('_test.py') or '.test.' in base or base.endswith('_spec.'):
        return True
    return False


_SOURCE_EXTS = {
    'py', 'ts', 'tsx', 'js', 'jsx', 'go', 'rs', 'java', 'rb', 'php', 'cs',
    'swift', 'kt', 'scala', 'c', 'cpp', 'h', 'hpp', 'ex', 'exs',
}
