"""Tests for new Phase 1-5 features."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from argon.ci import CIBaseline, CIDiffer, CIQualityGates, CIReporter
from argon.engine.domain_ml import DOMAIN_PROTOTYPES, DomainDetector
from argon.engine.keywords import extract_task_keywords
from argon.engine.monorepo import MonorepoDetector
from argon.engine.selector import select_precision_symbols
from argon.engine.task_decomposer import TaskDecomposer

# ===================== Task Decomposition =====================

def test_task_decomposer_simple_task():
    decomposer = TaskDecomposer()
    subtasks = decomposer.decompose("fix expression parser bug in Rust solver")
    assert len(subtasks) == 1
    assert subtasks[0]['action'] == 'fix'
    assert 'parser' in subtasks[0]['keywords']


def test_task_decomposer_complex_task():
    decomposer = TaskDecomposer()
    subtasks = decomposer.decompose("add user authentication with JWT and email verification")
    assert len(subtasks) >= 2
    actions = [s['action'] for s in subtasks]
    assert 'add' in actions


def test_task_decomposer_cache():
    decomposer = TaskDecomposer()
    task = "fix payment timeout and add refund support"
    r1 = decomposer.decompose(task)
    r2 = decomposer.decompose(task)
    assert r1 == r2


def test_task_decomposer_merge_with_priority():
    decomposer = TaskDecomposer()
    sym1 = {'id': 'a.ts::foo', 'name': 'foo', 'selection_score': 5.0}
    sym2 = {'id': 'b.ts::bar', 'name': 'bar', 'selection_score': 3.0}
    sym3 = {'id': 'c.ts::baz', 'name': 'baz', 'selection_score': 7.0}

    results = [
        ("auth", [sym1, sym2]),
        ("payment", [sym2, sym3]),
    ]
    merged = decomposer.merge_with_priority(results)
    assert len(merged) == 3
    assert merged[0]['id'] == 'b.ts::bar'


def test_task_decomposer_spanish():
    decomposer = TaskDecomposer()
    subtasks = decomposer.decompose("arreglar bug de autenticacion y agregar soporte de pagos")
    assert len(subtasks) >= 2


# ===================== ML Domain Detection =====================

def test_domain_detector_initializes():
    detector = DomainDetector()
    assert len(detector._domain_names) > 10
    assert detector._prototype_vectors is not None


def test_domain_detector_calculator():
    detector = DomainDetector()
    symbols = [
        {'name': 'parse_expression', 'file': 'solver.rs', 'signature': 'fn parse_expression'},
        {'name': 'ExprParser', 'file': 'solver.rs', 'signature': 'struct ExprParser'},
        {'name': 'calculate', 'file': 'math.rs', 'signature': 'fn calculate'},
    ]
    domain, scores = detector.detect(symbols, [], [])
    assert domain == 'calculator'
    assert scores['calculator'] > scores['web_app']


def test_domain_detector_neural_simulation():
    detector = DomainDetector()
    symbols = [
        {'name': 'update_neural', 'file': 'brain.py', 'signature': 'def update_neural'},
        {'name': 'Neuron', 'file': 'brain.py', 'signature': 'class Neuron'},
        {'name': 'synapse', 'file': 'brain.py', 'signature': 'def synapse'},
        {'name': 'plasticity', 'file': 'brain.py', 'signature': 'def plasticity'},
    ]
    domain, scores = detector.detect(symbols, [], [])
    assert domain == 'neural_simulation'


def test_domain_detector_web_app():
    detector = DomainDetector()
    symbols = [
        {'name': 'router', 'file': 'app.ts', 'signature': 'const router'},
        {'name': 'controller', 'file': 'userController.ts', 'signature': 'class UserController'},
        {'name': 'middleware', 'file': 'auth.ts', 'signature': 'function authMiddleware'},
    ]
    domain, scores = detector.detect(symbols, [], [])
    assert domain == 'web_app'


def test_domain_detector_e_commerce():
    detector = DomainDetector()
    symbols = [
        {'name': 'checkout', 'file': 'checkout.ts', 'signature': 'function checkout'},
        {'name': 'PaymentProcessor', 'file': 'payment.ts', 'signature': 'class PaymentProcessor'},
        {'name': 'shipping', 'file': 'shipping.ts', 'signature': 'function shipping'},
    ]
    domain, scores = detector.detect(symbols, [], [])
    assert domain == 'e_commerce'


def test_domain_detector_auth():
    detector = DomainDetector()
    symbols = [
        {'name': 'authenticate', 'file': 'auth.ts', 'signature': 'function authenticate'},
        {'name': 'validateToken', 'file': 'auth.ts', 'signature': 'function validateToken'},
        {'name': 'SessionManager', 'file': 'session.ts', 'signature': 'class SessionManager'},
    ]
    domain, scores = detector.detect(symbols, [], [])
    assert domain == 'auth_system'


def test_domain_detector_all_domains_have_prototypes():
    detector = DomainDetector()
    for domain, prototypes in DOMAIN_PROTOTYPES.items():
        assert len(prototypes) > 0, f"Domain {domain} has no prototypes"
        for proto in prototypes:
            assert len(proto) > 10, f"Domain {domain} has short prototype: {proto}"


# ===================== Monorepo Detection =====================

def test_monorepo_detector_npm_workspaces(tmp_path):
    root = tmp_path / "monorepo"
    root.mkdir()
    os.makedirs(str(root / "packages" / "core"))
    os.makedirs(str(root / "packages" / "api"))

    with open(str(root / "package.json"), "w") as f:
        json.dump({"name": "test-monorepo", "workspaces": ["packages/*"]}, f)

    detector = MonorepoDetector(str(root))
    assert detector.detect()
    packages = detector.find_packages()
    assert len(packages) >= 2


def test_monorepo_detector_cargo_workspaces(tmp_path):
    root = tmp_path / "rust-monorepo"
    root.mkdir()
    os.makedirs(str(root / "core"))
    os.makedirs(str(root / "cli"))

    with open(str(root / "Cargo.toml"), "w") as f:
        f.write("[workspace]\nmembers = [\n  \"core\",\n  \"cli\"\n]\n")

    detector = MonorepoDetector(str(root))
    packages = detector.find_packages()
    assert len(packages) >= 2


def test_monorepo_detector_not_monorepo(tmp_path):
    root = tmp_path / "simple"
    root.mkdir()

    detector = MonorepoDetector(str(root))
    assert not detector.detect()
    assert detector.find_packages() == []


# ===================== CI Quality Gates =====================

def test_ci_baseline_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        baseline = CIBaseline(tmp)
        data = {
            'files': ['a.ts', 'b.ts'],
            'symbol_ids': ['a.ts::foo', 'b.ts::bar'],
            'edges': [{'source': 'a.ts::foo', 'target': 'b.ts::bar'}],
            'file_hashes': {'a.ts': 'abc', 'b.ts': 'def'},
            'cycles': [],
        }
        baseline.save(data)
        assert baseline.exists()

        loaded = baseline.load()
        assert loaded is not None
        assert loaded['files'] == ['a.ts', 'b.ts']


def test_ci_differ_new_file():
    baseline = {'files': ['a.ts'], 'symbol_ids': ['a.ts::foo'], 'edges': [],
                'file_hashes': {}, 'cycles': []}
    current = {'files': ['a.ts', 'b.ts'], 'symbol_ids': ['a.ts::foo', 'b.ts::bar'],
               'edges': [], 'file_hashes': {}, 'cycles': []}
    differ = CIDiffer(baseline, current)
    diff = differ.diff()
    assert diff['summary']['files_added'] == 1
    assert diff['new_files'] == ['b.ts']
    assert diff['removed_files'] == []


def test_ci_differ_removed_symbol():
    baseline = {'files': ['a.ts'], 'symbol_ids': ['a.ts::foo', 'a.ts::bar'],
                'edges': [], 'file_hashes': {}, 'cycles': []}
    current = {'files': ['a.ts'], 'symbol_ids': ['a.ts::foo'],
               'edges': [], 'file_hashes': {}, 'cycles': []}
    differ = CIDiffer(baseline, current)
    diff = differ.diff()
    assert diff['summary']['symbols_removed'] == 1


def test_ci_quality_gates_pass():
    gates = CIQualityGates(max_new_cycles=0)
    diff = {
        'new_files': ['new.ts'], 'removed_files': [], 'changed_files': [],
        'new_symbols': ['new.ts::foo'], 'removed_symbols': [],
        'new_edges': 0, 'removed_edges': 0, 'new_cycles': [],
        'summary': {'files_added': 1, 'files_removed': 0, 'files_changed': 0,
                    'symbols_added': 1, 'symbols_removed': 0,
                    'edges_added': 0, 'edges_removed': 0, 'cycles_added': 0},
    }
    passed, violations = gates.check(diff)
    assert passed
    assert len(violations) == 0


def test_ci_quality_gates_fail_cycles():
    gates = CIQualityGates(max_new_cycles=0)
    diff = {
        'new_files': [], 'removed_files': [], 'changed_files': [],
        'new_symbols': [], 'removed_symbols': [],
        'new_edges': 0, 'removed_edges': 0,
        'new_cycles': ['a -> b -> a'],
        'summary': {'files_added': 0, 'files_removed': 0, 'files_changed': 0,
                    'symbols_added': 0, 'symbols_removed': 0,
                    'edges_added': 0, 'edges_removed': 0, 'cycles_added': 1},
    }
    passed, violations = gates.check(diff)
    assert not passed
    assert len(violations) > 0


def test_ci_reporter_generates_report():
    diff = {
        'new_files': ['new.ts'], 'removed_files': ['old.ts'], 'changed_files': [],
        'new_symbols': ['new.ts::foo'], 'removed_symbols': ['old.ts::bar'],
        'new_edges': 1, 'removed_edges': 0, 'new_cycles': [],
        'summary': {'files_added': 1, 'files_removed': 1, 'files_changed': 0,
                    'symbols_added': 1, 'symbols_removed': 1,
                    'edges_added': 1, 'edges_removed': 0, 'cycles_added': 0},
    }
    reporter = CIReporter("/tmp/test")
    report = reporter.generate_report(diff, (True, []))
    assert "PASSED" in report
    assert "Files added: 1" in report
    assert "Files removed: 1" in report


# ===================== Cross-Language Import Resolution =====================

def test_go_resolver_initialization():
    from argon.resolvers.go import GoResolver
    resolver = GoResolver("/tmp/test")
    assert resolver.root == "/tmp/test"


def test_java_resolver_initialization():
    from argon.resolvers.java import JavaResolver
    resolver = JavaResolver("/tmp/test")
    assert resolver.root == "/tmp/test"


def test_csharp_resolver_initialization(tmp_path):
    from argon.resolvers.csharp import CSharpResolver
    resolver = CSharpResolver(str(tmp_path))
    assert resolver.root == str(tmp_path)


def test_import_resolver_supports_new_languages():
    from argon.resolvers.imports import ImportResolver
    assert '.go' in ImportResolver.CODE_EXTS
    assert '.java' in ImportResolver.CODE_EXTS
    assert '.cs' in ImportResolver.CODE_EXTS


# ===================== Keyword Extraction =====================

def test_keyword_extraction_basic():
    keywords = extract_task_keywords("fix authentication bug")
    assert 'authentication' in keywords or 'auth' in keywords
    assert 'bug' in keywords


def test_keyword_extraction_synonyms():
    keywords = extract_task_keywords("fix login issue")
    assert 'login' in keywords
    assert 'auth' in keywords or 'authenticate' in keywords


def test_keyword_extraction_empty():
    keywords = extract_task_keywords("")
    assert keywords == []


# ===================== Domain Functions =====================

def test_detect_project_domain_ml_import():
    from argon.engine.domain import detect_project_domain_ml
    assert callable(detect_project_domain_ml)


def test_detect_project_domain_keywords_import():
    from argon.engine.domain import detect_project_domain
    assert callable(detect_project_domain)


# ===================== Domain-Aware AI Safeguards & Guardrails =====================

def test_domain_aware_safeguards_generation():
    from argon.engine.formatter import (
        build_precision_compact,
        build_precision_json_payload,
        generate_precision_context,
        get_domain_safeguards,
    )
    from argon.engine.graph import ArgonEngine
    from argon.utils.tokens import TokenCounter

    # 1. Test get_domain_safeguards logic directly
    rules_rs_sim = get_domain_safeguards('scientific_computing', {'rs'})
    assert any("STRUCTURAL THINKING:" in r for r in rules_rs_sim)
    assert any("SCOPE PINNING (RUST):" in r for r in rules_rs_sim)
    assert any("TYPE SAFETY (RUST):" in r for r in rules_rs_sim)
    assert any("NUMERICAL DAMPING" in r for r in rules_rs_sim)

    rules_py_non_sim = get_domain_safeguards('web_app', {'py'})
    assert any("STRUCTURAL THINKING:" in r for r in rules_py_non_sim)
    assert any("SCOPE PINNING:" in r for r in rules_py_non_sim)
    assert not any("RUST" in r for r in rules_py_non_sim)
    assert not any("NUMERICAL DAMPING" in r for r in rules_py_non_sim)

    # Mock Graph
    graph = {
        "root": "test-repo",
        "project_domain": "scientific_computing",
        "nodes": [
            {"id": "solver.rs", "type": "rs", "lines": 100},
            {"id": "main.rs", "type": "rs", "lines": 50}
        ],
        "edges": [],
        "symbol_edges": [],
        "stats": {
            "total_files": 2,
            "total_connections": 0,
            "total_symbols": 0,
            "total_symbol_connections": 0,
            "timestamp": "2026-06-22",
        },
        "preferred_file": "solver.rs",
    }

    counter = TokenCounter(model='gpt-4.1', strict=False)

    # 2. Test JSON builder
    json_payload = build_precision_json_payload(
        graph=graph,
        task="fix solver bug",
        max_tokens=2048,
        counter=counter,
    )
    data = json.loads(json_payload)
    assert "safeguards" in data
    assert len(data["safeguards"]) > 0
    assert any("pnjlim" in r for r in data["safeguards"])

    # 3. Test Compact builder
    compact_payload = build_precision_compact(
        graph=graph,
        task="fix solver bug",
        max_tokens=2048,
    )
    assert "# safeguard: " in compact_payload
    assert "pnjlim" in compact_payload

    # 4. Test XML & Markdown file output via generate_precision_context
    with tempfile.TemporaryDirectory() as tmp_dir:
        xml_path = os.path.join(tmp_dir, "context.xml")
        md_path = os.path.join(tmp_dir, "context.md")

        # XML
        generate_precision_context(
            graph=graph,
            output_path=xml_path,
            task="fix solver bug",
            max_tokens=2048,
            output_format="xml",
            counter=counter,
        )
        assert os.path.exists(xml_path)
        with open(xml_path, encoding='utf-8') as f:
            xml_content = f.read()
        assert "<safeguards>" in xml_content
        assert "<rule>" in xml_content
        assert "pnjlim" in xml_content

        # Markdown
        generate_precision_context(
            graph=graph,
            output_path=md_path,
            task="fix solver bug",
            max_tokens=2048,
            output_format="markdown",
            counter=counter,
        )
        assert os.path.exists(md_path)
        with open(md_path, encoding='utf-8') as f:
            md_content = f.read()
        assert "## AI CODING SAFEGUARDS" in md_content
        assert "pnjlim" in md_content

        # Test engine-level generate_precision_context (XML)
        engine = ArgonEngine(tmp_dir, precision=True)
        xml_path2 = os.path.join(tmp_dir, "context2.xml")
        engine.generate_precision_context(
            graph=graph,
            output_path=xml_path2,
            task="fix solver bug",
            max_tokens=2048,
            output_format="xml",
        )
        with open(xml_path2, encoding='utf-8') as f:
            xml_content2 = f.read()
        assert "<safeguards>" in xml_content2
        assert "pnjlim" in xml_content2

        # Test engine-level generate_precision_context (Markdown)
        md_path2 = os.path.join(tmp_dir, "context2.md")
        engine.generate_precision_context(
            graph=graph,
            output_path=md_path2,
            task="fix solver bug",
            max_tokens=2048,
            output_format="markdown",
        )
        with open(md_path2, encoding='utf-8') as f:
            md_content2 = f.read()
        assert "## AI CODING SAFEGUARDS" in md_content2
        assert "pnjlim" in md_content2

    # 5. Test ArgonEngine generate_context_report (ARGON.md)
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_path = os.path.join(tmp_dir, "ARGON.md")
        engine = ArgonEngine(tmp_dir, precision=True)
        engine.generate_context_report(graph, report_path)
        assert os.path.exists(report_path)
        with open(report_path, encoding='utf-8') as f:
            report_content = f.read()
        assert "## AI CODING SAFEGUARDS" in report_content
        assert "pnjlim" in report_content


# ===================== Dynamic File & Symbol Slicing =====================

def test_dynamic_slicing_large_function():
    from argon.engine.snippets import slice_symbol_body

    # 1. Test short function is not sliced
    short_code = [
        "fn add(a: i32, b: i32) -> i32 {",
        "    a + b",
        "}"
    ]
    assert slice_symbol_body(short_code, [], "rs") == "\n".join(short_code)

    # 2. Test large function gets sliced and collapsed
    large_code = [
        "fn large_solver_helper(x: &mut DVector<f64>) -> Result<(), String> {",
        "    let mut steps = 0;",
        "    let boring_var_1 = 1;",
        "    let boring_var_2 = 2;",
        "    let boring_var_3 = 3;",
        "    let boring_var_4 = 4;",
        "    let boring_var_5 = 5;",
        "    let boring_var_6 = 6;",
        "    let boring_var_7 = 7;",
        "    let boring_var_8 = 8;",
        "    if steps > 100 {",
        "        return Err(\"Max steps reached\".to_string());",
        "    }",
        "    let boring_var_9 = 9;",
        "    let boring_var_10 = 10;",
        "    let boring_var_11 = 11;",
        "    let boring_var_12 = 12;",
        "    let boring_var_13 = 13;",
        "    let boring_var_14 = 14;",
        "    let boring_var_15 = 15;",
        "    let boring_var_16 = 16;",
        "    let boring_var_17 = 17;",
        "    let boring_var_18 = 18;",
        "    execute_jacobian_update(x);",
        "    let boring_var_19 = 19;",
        "    let boring_var_20 = 20;",
        "    let boring_var_21 = 21;",
        "    let boring_var_22 = 22;",
        "    let boring_var_23 = 23;",
        "    Ok(())",
        "}"
    ]
    sliced = slice_symbol_body(large_code, ["jacobian"], "rs")

    assert "fn large_solver_helper" in sliced
    assert "if steps > 100 {" in sliced
    assert "execute_jacobian_update(x);" in sliced
    assert "Ok(())" in sliced
    assert "// ... [omitted" in sliced

    sliced_py = slice_symbol_body(large_code, ["jacobian"], "py")
    assert "# ... [omitted" in sliced_py


# ===================== Architectural Overhaul Improvements =====================

def test_architectural_overhaul_improvements():
    from argon.engine.builder import _pagerank
    from argon.parser.tree_sitter import TreeSitterAdapter
    from argon.utils.tokens import TokenCounter

    # 1. Test TreeSitterAdapter
    class FakeNode:
        def __init__(self, text):
            self.text = text

    assert TreeSitterAdapter.decode_text(FakeNode(b"hello")) == "hello"
    assert TreeSitterAdapter.decode_text(FakeNode("world")) == "world"

    class FakeTree:
        def __init__(self, root_callable=False):
            if root_callable:
                self.root_node = lambda: "root_val"
            else:
                self.root_node = "root_val"

    assert TreeSitterAdapter.get_root(FakeTree(root_callable=True)) == "root_val"
    assert TreeSitterAdapter.get_root(FakeTree(root_callable=False)) == "root_val"

    # 2. Test Optimized PageRank
    nodes = ["A", "B", "C"]
    edges = [{"source": "A", "target": "B"}, {"source": "B", "target": "C"}]
    ranks = _pagerank(nodes, edges)
    assert len(ranks) == 3
    assert ranks["C"] == 1.0
    assert ranks["A"] < ranks["B"]

    # 3. Test Multimodel TokenCounter
    gpt_counter = TokenCounter(model="gpt-4", strict=False)
    assert gpt_counter.is_gemini is False
    assert gpt_counter.is_claude is False

    gemini_counter = TokenCounter(model="gemini-1.5-pro", strict=False)
    assert gemini_counter.is_gemini is True
    assert gemini_counter.count("hello world") == 2

    claude_counter = TokenCounter(model="claude-3-5-sonnet", strict=False)
    assert claude_counter.is_claude is True
    assert claude_counter.count("hello world") >= 2


# ===================== Type-Aware Context Expansion =====================

def test_type_aware_context_expansion():

    graph = {
        "root": "test-repo",
        "project_domain": "general",
        "nodes": [
            {"id": "main.rs", "type": "rs", "lines": 50},
            {"id": "types.rs", "type": "rs", "lines": 30}
        ],
        "edges": [],
        "symbol_edges": [],
        "symbols": [
            {
                "id": "main.rs::solve_dc",
                "name": "solve_dc",
                "kind": "func",
                "file": "main.rs",
                "start_line": 1,
                "end_line": 5,
                "signature": "fn solve_dc(state: &mut NewtonState) -> Result<(), String>",
                "exported": True,
                "rank": 0.9,
                "inbound_calls": 0,
                "outbound_calls": 0,
            },
            {
                "id": "types.rs::NewtonState",
                "name": "NewtonState",
                "kind": "struct",
                "file": "types.rs",
                "start_line": 10,
                "end_line": 20,
                "signature": "struct NewtonState { size: usize }",
                "exported": True,
                "rank": 0.1,
                "inbound_calls": 0,
                "outbound_calls": 0,
            }
        ]
    }

    selected, report = select_precision_symbols(
        graph=graph,
        task="solve dc",
        max_tokens=0,
    )

    selected_ids = {s["id"] for s in selected}
    assert "main.rs::solve_dc" in selected_ids
    assert "types.rs::NewtonState" in selected_ids

    newton_state_sym = next(s for s in selected if s["id"] == "types.rs::NewtonState")
    assert "type_dependency" in newton_state_sym.get("selection_reasons", [])

    selected_budget, report_budget = select_precision_symbols(
        graph=graph,
        task="solve dc",
        max_tokens=20,
    )
    assert report_budget.get("omitted_by_budget", 0) > 0
    assert "budget_recommendation" in report_budget
