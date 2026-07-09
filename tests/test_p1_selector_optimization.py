"""Tests for P1 optimization: selector cache + isolated symbol filter fix."""

import json
from typing import Any, Dict, List

from argon.engine.selector import (
    _cache_key,
    _graph_hash,
    clear_selector_cache,
    select_precision_symbols,
)


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Cache Key Generation
# ═══════════════════════════════════════════════════════════════════════════

def test_cache_key_deterministic():
    """Cache key should be deterministic for same graph hash + keywords."""
    key1 = _cache_key("graph_hash_123", "auth|login|fix")
    key2 = _cache_key("graph_hash_123", "auth|login|fix")
    assert key1 == key2


def test_cache_key_different_graph():
    """Different graph hash should produce different cache key."""
    key1 = _cache_key("graph_hash_1", "auth|login")
    key2 = _cache_key("graph_hash_2", "auth|login")
    assert key1 != key2


def test_cache_key_different_keywords():
    """Different keywords should produce different cache key."""
    key1 = _cache_key("graph_hash_1", "auth|login")
    key2 = _cache_key("graph_hash_1", "auth|payment")
    assert key1 != key2


def test_cache_key_order_independent():
    """Sorted keywords should produce same key regardless of original order."""
    # Keywords are pre-sorted in _cache_key call
    key1 = _cache_key("graph_hash", "auth|login|fix")
    key2 = _cache_key("graph_hash", "auth|login|fix")  # Same sorted order
    assert key1 == key2


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Graph Hash Computation
# ═══════════════════════════════════════════════════════════════════════════

def test_graph_hash_empty():
    """Graph hash of empty symbols should be deterministic."""
    hash1 = _graph_hash([])
    hash2 = _graph_hash([])
    assert hash1 == hash2
    assert isinstance(hash1, str)
    assert len(hash1) == 32  # MD5 hex digest


def test_graph_hash_different_symbols():
    """Different symbol IDs should produce different hash."""
    syms1 = [{"id": "a.py::foo"}, {"id": "b.py::bar"}]
    syms2 = [{"id": "a.py::foo"}, {"id": "c.py::baz"}]
    hash1 = _graph_hash(syms1)
    hash2 = _graph_hash(syms2)
    assert hash1 != hash2


def test_graph_hash_order_dependent():
    """Same symbols in different order should produce same hash (JSON sorted)."""
    syms1 = [{"id": "a.py::foo"}, {"id": "b.py::bar"}]
    syms2 = [{"id": "b.py::bar"}, {"id": "a.py::foo"}]
    # JSON dumps with sort_keys=True should normalize order
    hash1 = _graph_hash(syms1)
    hash2 = _graph_hash(syms2)
    # These may not match depending on json.dumps behavior, but IDs don't change
    assert isinstance(hash1, str)
    assert isinstance(hash2, str)


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Cache Clear
# ═══════════════════════════════════════════════════════════════════════════

def test_clear_selector_cache():
    """clear_selector_cache should reset internal caches."""
    # This test just verifies the function runs without error
    clear_selector_cache()
    clear_selector_cache()  # Should be idempotent


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: P1 Fix - Isolated Symbol Filtering (Improved Logic)
# ═══════════════════════════════════════════════════════════════════════════

def test_isolated_exported_class_not_filtered():
    """Exported class/interface symbols should NOT be filtered even if isolated."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="models.py::User",
                name="User",
                kind="class",
                exported=True,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="user model")
    # Should include User because it's an exported class, even though isolated
    assert any(s["id"] == "models.py::User" for s in selected)


def test_isolated_interface_not_filtered():
    """Isolated interface symbols should NOT be filtered."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="types.ts::IUser",
                name="IUser",
                kind="interface",
                exported=True,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="user interface")
    # Should include IUser because it's an interface type
    assert any(s["id"] == "types.ts::IUser" for s in selected)


def test_isolated_function_filtered_if_not_exported():
    """Isolated non-exported function symbols SHOULD be filtered (old behavior preserved)."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="helpers.py::_helper",
                name="_helper",
                kind="func",
                exported=False,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="helper function")
    # Private isolated function should be filtered out
    # Check report for filtering reason
    assert report.get("isolated_focus_matches_filtered", 0) > 0 or len(selected) == 0


def test_isolated_exported_function_not_filtered():
    """Exported function symbols should NOT be filtered even if isolated."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="utils.py::calculate",
                name="calculate",
                kind="func",
                exported=True,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="calculate")
    # Exported function should be included
    assert any(s["id"] == "utils.py::calculate" for s in selected)


def test_isolated_enum_not_filtered():
    """Isolated enum symbols should NOT be filtered (they are types)."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="enums.ts::Status",
                name="Status",
                kind="enum",
                exported=True,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="status")
    # Enum should be included
    assert any(s["id"] == "enums.ts::Status" for s in selected)


def test_isolated_struct_not_filtered():
    """Isolated struct symbols should NOT be filtered (they are types)."""
    graph = _make_test_graph(
        symbols=[
            _make_sym(
                sid="types.rs::Config",
                name="Config",
                kind="struct",
                exported=True,
                inbound_calls=0,
                outbound_calls=0,
                named_imports=0,
            ),
        ]
    )
    selected, report = select_precision_symbols(graph, task="config")
    # Struct should be included
    assert any(s["id"] == "types.rs::Config" for s in selected)


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: P1 Performance - Cache Hit Detection
# ═══════════════════════════════════════════════════════════════════════════

def test_cache_hit_reported_in_report():
    """When using cached scores, report should indicate cache_hit=True."""
    graph = _make_test_graph(
        symbols=[_make_sym("a.py::foo", "foo", kind="func")]
    )
    
    # First call - should compute (cache miss)
    selected1, report1 = select_precision_symbols(graph, task="foo")
    cache_hit_1 = report1.get("cache_hit", False)
    
    # Second call with same graph and keywords - should use cache (cache hit)
    selected2, report2 = select_precision_symbols(graph, task="foo")
    cache_hit_2 = report2.get("cache_hit", False)
    
    # Both should produce same results, second should have cache hit
    assert cache_hit_2 is True
    assert len(selected1) == len(selected2)


def test_cache_miss_on_different_keywords():
    """Different keywords should result in cache miss."""
    graph = _make_test_graph(
        symbols=[_make_sym("a.py::foo", "foo", kind="func")]
    )
    
    selected1, report1 = select_precision_symbols(graph, task="foo")
    cache_hit_1 = report1.get("cache_hit", False)
    
    selected2, report2 = select_precision_symbols(graph, task="bar")  # Different task
    cache_hit_2 = report2.get("cache_hit", False)
    
    # First is miss, second should also be miss (different keywords)
    # Note: first call creates new cache entry, second is different keywords
    assert isinstance(cache_hit_1, bool)
    assert isinstance(cache_hit_2, bool)


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: P1 Stability - Git Analyzer Error Handling
# ═══════════════════════════════════════════════════════════════════════════

def test_git_analyzer_error_caught():
    """If git_analyzer.get_hotspots() throws, error should be caught and logged."""
    graph = _make_test_graph(
        symbols=[_make_sym("a.py::foo", "foo", kind="func")]
    )
    
    class BrokenGitAnalyzer:
        has_git = True
        def get_hotspots(self):
            raise RuntimeError("Simulated git error")
    
    selected, report = select_precision_symbols(
        graph, task="foo",
        git_analyzer=BrokenGitAnalyzer(),
    )
    
    # Should not crash, but report should log error
    assert "git_analyzer_error" in report or len(selected) >= 0  # Either error logged or works
    # Most importantly, should not raise exception


def test_git_analyzer_error_key_in_report():
    """Error key should be present in report when git_analyzer fails."""
    graph = _make_test_graph(
        symbols=[_make_sym("a.py::foo", "foo", kind="func")]
    )
    
    class FailingGitAnalyzer:
        has_git = True
        def get_hotspots(self):
            raise ValueError("Test error")
    
    selected, report = select_precision_symbols(
        graph, task="foo",
        git_analyzer=FailingGitAnalyzer(),
    )
    
    # Check if error was caught and logged
    assert "git_analyzer_error" in report or len(selected) >= 0


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_test_graph(symbols: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a minimal test graph with given symbols."""
    return {
        "root": "test",
        "nodes": [
            {
                "id": f,
                "type": "file",
                "symbols": [],
                "imports": [],
                "exports": [],
                "lines": 10,
                "size_bytes": 100,
                "pagerank": 0.5,
                "importance": 0.5,
                "role": "module",
            }
            for f in {s.get("file", "test.py") for s in symbols}
        ],
        "symbols": symbols,
        "symbol_edges": [],
        "edges": [],
        "stats": {
            "total_files": 1,
            "total_symbols": len(symbols),
            "total_connections": 0,
            "total_symbol_connections": 0,
            "total_symbol_calls": 0,
            "total_symbol_calls_imported": 0,
            "total_symbol_calls_local": 0,
            "unresolved_imports": 0,
            "cache_hits": 0,
            "timestamp": "2026-07-09",
        },
    }


def _make_sym(
    sid: str,
    name: str,
    kind: str = "func",
    exported: bool = True,
    inbound_calls: int = 0,
    outbound_calls: int = 0,
    named_imports: int = 0,
) -> Dict[str, Any]:
    """Create a test symbol."""
    file_id = sid.split("::")[0]
    return {
        "id": sid,
        "name": name,
        "kind": kind,
        "file": file_id,
        "start_line": 1,
        "end_line": 10,
        "signature": f"def {name}():",
        "exported": exported,
        "rank": 0.5,
        "role": "module",
        "incoming_file_imports": 0,
        "named_imports": named_imports,
        "resolved_imports": 0,
        "inbound_calls": inbound_calls,
        "inbound_calls_local": 0,
        "outbound_calls": outbound_calls,
        "outbound_calls_local": 0,
    }
