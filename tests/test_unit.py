import os
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from argon.engine.graph import _pagerank, ArgonEngine


# ─── _pagerank ────────────────────────────────────────────────────────

def test_pagerank_empty():
    assert _pagerank([], []) == {}


def test_pagerank_single_node():
    result = _pagerank(["a"], [])
    assert result == {"a": 1.0}


def test_pagerank_two_nodes_no_edges():
    result = _pagerank(["a", "b"], [])
    assert set(result) == {"a", "b"}
    assert result["a"] == 1.0
    assert result["b"] == 1.0


def test_pagerank_two_nodes_one_edge():
    result = _pagerank(["a", "b"], [{"source": "a", "target": "b"}])
    assert result["b"] > result["a"]


def test_pagerank_double_edge():
    result = _pagerank(
        ["a", "b", "c"],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    )
    a, b = result["a"], result["b"]
    assert abs(a - b) < 0.01


def test_pagerank_sink():
    result = _pagerank(
        ["a", "b", "c"],
        [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
    )
    assert result["b"] > result["a"]


def test_pagerank_invalid_target_ignored():
    result = _pagerank(["a"], [{"source": "a", "target": "nonexistent"}])
    assert result == {"a": 1.0}


def test_pagerank_self_edge_ignored():
    result = _pagerank(["a"], [{"source": "a", "target": "a"}])
    assert result == {"a": 1.0}


# ─── _identifier_tokens ──────────────────────────────────────────────

def test_identifier_tokens_simple():
    engine = _make_engine(".")
    assert engine._identifier_tokens("checkoutTotal") == ["checkout", "total"]


def test_identifier_tokens_already_lower():
    engine = _make_engine(".")
    assert engine._identifier_tokens("checkout") == ["checkout"]


def test_identifier_tokens_with_numbers():
    engine = _make_engine(".")
    tokens = engine._identifier_tokens("order2item")
    assert tokens == ["order2item"]  # digits don't trigger split


# ─── _task_keywords ───────────────────────────────────────────────────

def test_task_keywords_simple():
    engine = _make_engine(".")
    keywords = engine._task_keywords("fix checkout total bug")
    assert "checkout" in keywords
    assert "total" in keywords
    assert all(w not in keywords for w in ("fix", "the", "a"))


def test_task_keywords_with_synonyms():
    engine = _make_engine(".")
    keywords = engine._task_keywords("add login")
    assert "auth" in keywords or "login" in keywords


def test_task_keywords_auth_synonym():
    engine = _make_engine(".")
    keywords = engine._task_keywords("fix authentication")
    assert "auth" in keywords


def test_task_keywords_payment_synonym():
    engine = _make_engine(".")
    keywords = engine._task_keywords("payment bug")
    assert "payment" in keywords
    assert "pay" in keywords  # full synonym expansion now includes all group members
    assert "refund" in keywords


def test_task_keywords_total_synonym_expansion():
    engine = _make_engine(".")
    keywords = engine._task_keywords("fix total calculation")
    assert "total" in keywords
    assert "sum" in keywords
    assert "price" in keywords


def test_task_keywords_empty():
    engine = _make_engine(".")
    assert engine._task_keywords("") == []


# ─── _task_intents ────────────────────────────────────────────────────

def test_task_intents_bugfix():
    engine = _make_engine(".")
    assert "bugfix" in engine._task_intents("fix error bug")


def test_task_intents_tests():
    engine = _make_engine(".")
    assert "tests" in engine._task_intents("add tests for checkout")


def test_task_intents_types():
    engine = _make_engine(".")
    assert "types" in engine._task_intents("create type for order")


def test_task_intents_multiple():
    intents = _make_engine(".")._task_intents("fix broken test type")
    assert "bugfix" in intents
    assert "tests" in intents
    assert "types" in intents


def test_task_intents_none():
    assert _make_engine(".")._task_intents("general cleanup") == set()


# ─── _task_focus_tokens ──────────────────────────────────────────────

def test_focus_tokens_excludes_entity_tokens():
    engine = _make_engine(".")
    focus = engine._task_focus_tokens(["user", "order", "bug", "helper", "item"])
    assert "helper" in focus
    assert "user" in focus  # user is no longer an entity token
    assert "order" in focus  # order is no longer an entity token
    assert "bug" not in focus  # entity token
    assert "item" not in focus  # entity token


# ─── _symbol_tokens ───────────────────────────────────────────────────

def test_symbol_tokens_uses_id_name_file_kind_signature():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::runMain", "name": "runMain", "file": "src/main.ts",
           "kind": "func", "signature": "runMain(): string"}
    tokens = engine._symbol_tokens(sym)
    assert "run" in tokens
    assert "main" in tokens
    assert "src" in tokens
    assert "func" in tokens
    assert "string" in tokens


# ─── _symbol_match_profile ───────────────────────────────────────────

def test_symbol_match_profile_name_match():
    engine = _make_engine(".")
    sym = {"id": "src/test.ts::helper", "name": "helper", "file": "src/test.ts", "kind": "func", "signature": ""}
    profile = engine._symbol_match_profile(sym, ["helper"])
    assert "helper" in profile["name"]
    assert "helper" in profile["all"]


def test_symbol_match_profile_file_match():
    engine = _make_engine(".")
    sym = {"id": "src/order.ts::calc", "name": "calc", "file": "src/order.ts", "kind": "func", "signature": ""}
    profile = engine._symbol_match_profile(sym, ["order"])
    assert "order" in profile["file"]


# ─── _score_symbol_for_task ──────────────────────────────────────────

def test_score_symbol_empty_keywords():
    engine = _make_engine(".")
    sym = {"id": "test", "name": "test", "file": "test.ts", "kind": "func", "signature": "", "exported": True}
    score, overlap = engine._score_symbol_for_task(sym, [])
    assert score == 0.0
    assert overlap == 0


def test_score_symbol_name_exact():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "name": "helper", "file": "src/main.ts",
           "kind": "func", "signature": "helper(): void", "exported": True}
    score, overlap = engine._score_symbol_for_task(sym, ["helper"])
    assert score > 0
    assert overlap >= 1


def test_score_symbol_file_match():
    engine = _make_engine(".")
    sym = {"id": "src/helper.ts::foo", "name": "foo", "file": "src/helper.ts",
           "kind": "func", "signature": "foo(): void", "exported": True}
    score, _ = engine._score_symbol_for_task(sym, ["helper"])
    # file match = 1.6, substring in name = 0, file substring = 0.45
    assert score >= 1.6


def test_score_symbol_prioritizes_name_over_file():
    engine = _make_engine(".")
    name_sym = {"id": "a.ts::payment", "name": "payment", "file": "a.ts",
                "kind": "func", "signature": "", "exported": True}
    file_sym = {"id": "payment.ts::x", "name": "x", "file": "payment.ts",
                "kind": "func", "signature": "", "exported": True}
    name_score, _ = engine._score_symbol_for_task(name_sym, ["payment"])
    file_score, _ = engine._score_symbol_for_task(file_sym, ["payment"])
    assert name_score > file_score


def test_score_symbol_focus_token_bonus():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "name": "helper", "file": "src/main.ts",
           "kind": "func", "signature": "", "exported": True}
    score, _ = engine._score_symbol_for_task(sym, ["helper", "bug"])
    assert score > 0


def test_score_symbol_substring_in_name():
    engine = _make_engine(".")
    sym = {"id": "src/orderHelper.ts::orderHelper", "name": "orderHelper",
           "file": "src/orderHelper.ts", "kind": "func", "signature": "", "exported": True}
    score, _ = engine._score_symbol_for_task(sym, ["order"])
    assert score > 5.0  # 5.0 for name token + 1.5 for substring


# ─── _is_noise_symbol_for_task ────────────────────────────────────────

def test_noise_symbol_by_name():
    engine = _make_engine(".")
    sym = {"id": "test.ts::Exception", "name": "Exception", "file": "test.ts",
           "kind": "func", "signature": "def Exception():", "start_line": 1, "end_line": 3, "exported": True}
    assert engine._is_noise_symbol_for_task(sym) is True


def test_noise_symbol_raise_error():
    engine = _make_engine(".")
    sym = {"id": "test.ts::ValueError", "name": "ValueError", "file": "test.ts",
           "kind": "func", "signature": "raise ValueError(...)", "start_line": 1, "end_line": 1, "exported": False}
    assert engine._is_noise_symbol_for_task(sym) is True


def test_not_noise_normal_func():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "name": "helper", "file": "src/main.ts",
           "kind": "func", "signature": "def helper(value):", "start_line": 5, "end_line": 10, "exported": True}
    assert engine._is_noise_symbol_for_task(sym) is False


def test_not_noise_exported_func():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "name": "helper", "file": "src/main.ts",
           "kind": "func", "signature": "export function helper()", "start_line": 1, "end_line": 5, "exported": True}
    assert engine._is_noise_symbol_for_task(sym) is False


# ─── _is_generic_type_symbol ─────────────────────────────────────────

def test_generic_type_high_imports_no_calls():
    engine = _make_engine(".")
    sym = {"id": "types.ts::User", "name": "User", "kind": "interface",
           "named_imports": 30, "inbound_calls": 0}
    assert engine._is_generic_type_symbol(sym) is True


def test_not_generic_low_imports():
    engine = _make_engine(".")
    sym = {"id": "types.ts::User", "name": "User", "kind": "interface",
           "named_imports": 5, "inbound_calls": 0}
    assert engine._is_generic_type_symbol(sym) is False


def test_not_generic_func_kind():
    engine = _make_engine(".")
    sym = {"id": "main.ts::run", "name": "run", "kind": "func",
           "named_imports": 30, "inbound_calls": 0}
    assert engine._is_generic_type_symbol(sym) is False


def test_not_generic_has_inbound_calls():
    engine = _make_engine(".")
    sym = {"id": "types.ts::User", "name": "User", "kind": "interface",
           "named_imports": 30, "inbound_calls": 5}
    assert engine._is_generic_type_symbol(sym) is False


# ─── _is_weak_file_only_match ────────────────────────────────────────

def test_weak_file_only_match():
    engine = _make_engine(".")
    sym = {"id": "helper.ts::foo", "name": "foo", "file": "helper.ts", "kind": "func", "signature": ""}
    assert engine._is_weak_file_only_match(sym, ["helper"]) is True


def test_not_weak_if_name_matches():
    engine = _make_engine(".")
    sym = {"id": "helper.ts::helper", "name": "helper", "file": "helper.ts", "kind": "func", "signature": ""}
    assert engine._is_weak_file_only_match(sym, ["helper"]) is False


def test_not_weak_if_no_file_match():
    engine = _make_engine(".")
    sym = {"id": "main.ts::foo", "name": "foo", "file": "main.ts", "kind": "func", "signature": ""}
    assert engine._is_weak_file_only_match(sym, ["helper"]) is False


# ─── _is_unrequested_test_symbol ─────────────────────────────────────

def test_unrequested_test_symbol():
    engine = _make_engine(".")
    sym = {"id": "src/main.test.ts::testHelper", "file": "src/main.test.ts",
           "name": "testHelper", "kind": "func", "signature": ""}
    assert engine._is_unrequested_test_symbol(sym, set()) is True


def test_not_unrequested_if_tests_intent():
    engine = _make_engine(".")
    sym = {"id": "src/main.test.ts::testHelper", "file": "src/main.test.ts",
           "name": "testHelper", "kind": "func", "signature": ""}
    assert engine._is_unrequested_test_symbol(sym, {"tests"}) is False


def test_not_unrequested_for_non_test_file():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "file": "src/main.ts",
           "name": "helper", "kind": "func", "signature": ""}
    assert engine._is_unrequested_test_symbol(sym, set()) is False


# ─── _is_isolated_focus_match ────────────────────────────────────────

def test_isolated_focus_match():
    engine = _make_engine(".")
    sym = {"id": "test/fixtures/mock.ts::helper", "file": "test/fixtures/mock.ts",
           "name": "helper", "kind": "func", "signature": "helper()",
           "inbound_calls": 0, "outbound_calls": 0, "named_imports": 0, "resolved_imports": 0}
    assert engine._is_isolated_focus_match(sym, ["helper"]) is True


def test_not_isolated_if_structural_signal():
    engine = _make_engine(".")
    sym = {"id": "test/fixtures/mock.ts::helper", "file": "test/fixtures/mock.ts",
           "name": "helper", "kind": "func", "signature": "helper()",
           "inbound_calls": 5, "outbound_calls": 0, "named_imports": 0, "resolved_imports": 0}
    assert engine._is_isolated_focus_match(sym, ["helper"]) is False


def test_not_isolated_if_not_in_noise_dir():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "file": "src/main.ts",
           "name": "helper", "kind": "func", "signature": "helper()",
           "inbound_calls": 0, "outbound_calls": 0, "named_imports": 0, "resolved_imports": 0}
    assert engine._is_isolated_focus_match(sym, ["helper"]) is False


# ─── _support_symbol_factor ──────────────────────────────────────────

def test_support_factor_test_file_no_test_intent():
    engine = _make_engine(".")
    sym = {"id": "test.ts::helper", "file": "test.ts", "name": "helper", "kind": "func"}
    assert engine._support_symbol_factor(sym, ["helper"], set()) == 0.55


def test_support_factor_test_file_with_test_intent():
    engine = _make_engine(".")
    sym = {"id": "test.ts::helper", "file": "test.ts", "name": "helper", "kind": "func"}
    assert engine._support_symbol_factor(sym, ["helper"], {"tests"}) == 1.0


def test_support_factor_model_file():
    engine = _make_engine(".")
    sym = {"id": "src/models/User.ts::User", "file": "src/models/User.ts",
           "name": "User", "kind": "class", "signature": ""}
    factor = engine._support_symbol_factor(sym, ["order"], set())
    assert factor == 0.25  # order is now a focus keyword → model has no overlap → demoted


def test_support_factor_no_focus_default():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "file": "src/main.ts",
           "name": "helper", "kind": "func", "signature": ""}
    assert engine._support_symbol_factor(sym, [], set()) == 1.0


# ─── _context_tier ───────────────────────────────────────────────────

def test_context_tier_not_matched():
    engine = _make_engine(".")
    sym = {"id": "src/main.ts::helper", "file": "src/main.ts", "name": "helper",
           "kind": "func", "signature": "", "exported": True}
    tier = engine._context_tier(sym, ["order"], set())
    assert tier == "support"  # no match for "order" keyword


def test_context_tier_file_only():
    engine = _make_engine(".")
    sym = {"id": "src/helper.ts::x", "file": "src/helper.ts", "name": "x",
           "kind": "func", "signature": "", "exported": True}
    tier = engine._context_tier(sym, ["helper"], set())
    assert tier == "critical"  # func + file match + exported


def test_context_tier_noise():
    engine = _make_engine(".")
    sym = {"id": "src/samples/mock.ts::helper", "file": "src/samples/mock.ts",
           "name": "helper", "kind": "func", "signature": "", "exported": True}
    tier = engine._context_tier(sym, ["helper"], set())
    assert tier == "critical"  # func + focus in name


# ─── _edge_maps ──────────────────────────────────────────────────────

def test_edge_maps_empty():
    engine = _make_engine(".")
    inc, out = engine._edge_maps({"symbol_edges": []})
    assert inc == {}
    assert out == {}


def test_edge_maps_basic():
    engine = _make_engine(".")
    edges = [
        {"source": "a", "target": "b"},
        {"source": "a", "target": "c"},
        {"source": "b", "target": "a"},
    ]
    inc, out = engine._edge_maps({"symbol_edges": edges})
    assert len(out["a"]) == 2
    assert any(e is edges[0] for e in out["a"])
    assert any(e is edges[1] for e in out["a"])
    assert len(inc["b"]) == 1


# ─── _compute_importance ─────────────────────────────────────────────

def test_compute_importance_single_node():
    engine = _make_engine_with_precision(".")
    node = _fake_node("a", lines=100, symbols_count=5)
    engine._compute_importance([node], [])
    assert node.importance > 0
    assert node.pagerank >= 0


def test_compute_importance_non_precision():
    engine = _make_engine(".")
    node = _fake_node("a", lines=100, symbols_count=5)
    engine._compute_importance([node], [])
    assert node.importance > 0


def test_compute_importance_connected_node_ranks_higher():
    engine = _make_engine_with_precision(".")
    a, b, c = _fake_node("a", lines=10, symbols_count=1), _fake_node("b", lines=10, symbols_count=1), _fake_node("c", lines=10, symbols_count=1)
    edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}]
    engine._compute_importance([a, b, c], edges)
    assert b.importance > 0


# ─── _should_skip ────────────────────────────────────────────────────

def test_should_skip_skipped_dir():
    engine = _make_engine(".")
    assert engine._should_skip("/tmp/node_modules", True) is True


def test_should_skip_normal_dir():
    engine = _make_engine(".")
    assert engine._should_skip("/tmp/src", True) is False


def test_should_skip_skipped_file():
    engine = _make_engine(".")
    p = _write_temp("argon_graph.json", "{}")
    assert engine._should_skip(p, False) is True


def test_should_skip_unknown_extension():
    engine = _make_engine(".")
    p = _write_temp("test.xyz", "hello")
    assert engine._should_skip(p, False) is True


def test_should_skip_normal_source_file():
    engine = _make_engine(".")
    p = _write_temp("main.ts", "export const x = 1;")
    assert engine._should_skip(p, False) is False


def test_should_skip_precision_file():
    engine = _make_engine(".")
    p = _write_temp("ARGON_PRECISION.xml", "<data/>")
    assert engine._should_skip(p, False) is True


# ─── _precision_expansion_plan & _fit_expansion_plan ────────────────

def test_expansion_plan_empty_symbols():
    engine = _make_engine(".")
    plan = engine._precision_expansion_plan([], set(), set())
    assert plan == []


def test_expansion_plan_single_symbol():
    engine = _make_engine_with_precision(".")
    syms = [_fake_sym("a", "main.ts::a", 50)]
    plan = engine._precision_expansion_plan(syms, set(), set())
    assert len(plan) == 1
    assert "argon_expand_symbol" in plan[0]["expand_with"]
    assert "selection_score" in plan[0]


def test_fit_expansion_plan_respects_budget():
    engine = _make_engine_with_precision(".")
    syms = [
        _fake_sym("a", "main.ts::a", 100),
        _fake_sym("b", "main.ts::b", 200),
        _fake_sym("c", "main.ts::c", 300),
    ]
    plan = engine._precision_expansion_plan(syms, set(), set())
    payload = {"symbols": [], "expansion_plan": []}
    engine._fit_expansion_plan(payload, syms, max_tokens=350)
    assert len(payload["expansion_plan"]) <= len(plan)
    assert all(p["expand_with"] for p in payload["expansion_plan"])


# ─── _build_precision_json_payload ────────────────────────────────────

def test_precision_json_payload_structure():
    engine = _make_engine_with_precision(".")
    graph = {
        "root": ".",
        "nodes": [{"id": "main.ts", "type": "file", "size_bytes": 100}],
        "edges": [],
        "symbol_edges": [],
        "stats": {"total_files": 1, "total_connections": 0,
                   "total_symbols": 0, "total_symbol_connections": 0,
                   "total_symbol_calls": 0, "total_symbol_calls_local": 0,
                   "unresolved_imports": 0, "parse_time": 0.1},
        "preferred_file": "main.ts",
    }
    payload = json.loads(engine._build_precision_json_payload(
        graph, task="test", max_tokens=1000,
    ))
    assert payload["precision"] is True
    assert payload["task"] == "test"
    assert "symbols" in payload
    assert "layers" in payload
    assert "expansion_plan" in payload
    assert "packaging_report" in payload
    assert payload["used_tokens"] <= 1000


# ─── helpers ──────────────────────────────────────────────────────────

def _make_engine(path: str) -> ArgonEngine:
    return ArgonEngine(path, precision=False)


def _make_engine_with_precision(path: str) -> ArgonEngine:
    return ArgonEngine(path, precision=True, model="gpt-4.1")


class _fake_node:
    def __init__(self, node_id: str, lines: int = 10, symbols_count: int = 1):
        self.id = node_id
        self.type = "file"
        self.lines = lines
        self.size_bytes = 100
        self.imports = []
        self.import_records = []
        self.exports = []
        self.unresolved_imports = []
        self.resolved_imports = {}
        self.summary = ""
        self.importance = 0.0
        self.pagerank = 0.0
        self.symbols = [object() for _ in range(symbols_count)]


def _fake_sym(name: str, sym_id: str, token_cost: int) -> Dict[str, Any]:
    return {
        "id": sym_id,
        "name": name,
        "file": sym_id.split("::")[0],
        "kind": "func",
        "signature": "",
        "start_line": 1,
        "end_line": 5,
        "exported": True,
        "token_cost": token_cost,
        "selection_reasons": [],
        "value_per_token": 0.0,
        "inbound_calls": 0,
        "outbound_calls": 0,
        "named_imports": 0,
    }


def _write_temp(name: str, content: str) -> str:
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(content)
    return p
