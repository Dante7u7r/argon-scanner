"""Tests for new Phase 1-5 features."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from argon.engine.task_decomposer import TaskDecomposer
from argon.engine.feedback import FeedbackStore
from argon.engine.incremental import IncrementalSelector
from argon.engine.domain_ml import DomainDetector, DOMAIN_PROTOTYPES
from argon.engine.monorepo import MonorepoDetector
from argon.engine.learned_scorer import LearnedScorer, extract_features
from argon.engine.gnn_scorer import SimpleGNN, extract_node_features, build_adjacency_list, HAS_NUMPY
from argon.engine.selector import select_precision_symbols
from argon.engine.keywords import extract_task_keywords
from argon.ci import CIBaseline, CIDiffer, CIQualityGates, CIReporter


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


# ===================== Feedback Store =====================

def test_feedback_store_record_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp:
        store = FeedbackStore(tmp)
        assert store.entry_count == 0
        assert not store.has_feedback()

        store.record(
            task="fix auth bug",
            accepted=["auth.ts::validateToken", "auth.ts::authenticate"],
            rejected=["cache.ts::cacheGet"],
        )
        assert store.entry_count == 1
        assert store.has_feedback()

        store.record(
            task="add payment support",
            accepted=["payment.ts::processPayment"],
            rejected=["auth.ts::loginUser"],
        )
        assert store.entry_count == 2

        accepted = store.get_accepted_symbols()
        assert "auth.ts::validateToken" in accepted
        assert "payment.ts::processPayment" in accepted

        rejected = store.get_rejected_symbols()
        assert "cache.ts::cacheGet" in rejected
        assert "auth.ts::loginUser" in rejected


def test_feedback_store_training_data():
    with tempfile.TemporaryDirectory() as tmp:
        store = FeedbackStore(tmp)
        store.record(task="t1", accepted=["a"], rejected=["b"])
        store.record(task="t2", accepted=["c"], rejected=["d"])

        data = store.get_training_data()
        assert len(data) == 2
        assert data[0]['task'] == "t1"
        assert data[1]['task'] == "t2"


def test_feedback_store_weights():
    with tempfile.TemporaryDirectory() as tmp:
        store = FeedbackStore(tmp)
        weights = {"model": "custom", "alpha": 0.5}
        store.save_weights(weights)
        loaded = store.load_weights()
        assert loaded == weights


def test_feedback_store_empty():
    with tempfile.TemporaryDirectory() as tmp:
        store = FeedbackStore(tmp)
        assert store.entry_count == 0
        assert not store.has_feedback()
        assert store.get_accepted_symbols() == set()
        assert store.get_rejected_symbols() == set()
        assert store.get_training_data() == []
        assert store.load_weights() == {}


# ===================== Incremental Context =====================

def test_incremental_selector_basic():
    symbols = [
        {'id': 'a.ts::validateToken', 'name': 'validateToken', 'kind': 'func', 'file': 'a.ts',
         'start_line': 10, 'end_line': 25, 'signature': 'function validateToken()', 'exported': True,
         'selection_score': 8.5, 'inbound_calls': 5, 'outbound_calls': 2},
        {'id': 'a.ts::authenticate', 'name': 'authenticate', 'kind': 'func', 'file': 'a.ts',
         'start_line': 30, 'end_line': 45, 'signature': 'function authenticate()', 'exported': True,
         'selection_score': 7.2, 'inbound_calls': 3, 'outbound_calls': 1},
        {'id': 'b.ts::User', 'name': 'User', 'kind': 'interface', 'file': 'b.ts',
         'start_line': 5, 'end_line': 15, 'signature': 'interface User {}', 'exported': True,
         'selection_score': 6.8, 'inbound_calls': 10, 'outbound_calls': 0},
    ]
    keywords = ['auth', 'token', 'validate']
    intents = {'bugfix'}
    selector = IncrementalSelector(symbols, keywords, intents, total_budget=100000)

    wave1 = selector.get_wave_symbols(0)
    assert len(wave1) > 0

    wave2 = selector.get_wave_symbols(1)
    assert len(wave2) >= len(wave1)

    wave3 = selector.get_wave_symbols(2)
    assert len(wave3) >= len(wave2)


def test_incremental_selector_expansion():
    symbols = [
        {'id': 'a.ts::foo', 'name': 'foo', 'kind': 'func', 'file': 'a.ts',
         'start_line': 1, 'end_line': 5, 'signature': 'function foo()', 'exported': True,
         'selection_score': 8.0, 'inbound_calls': 2, 'outbound_calls': 1},
        {'id': 'b.ts::bar', 'name': 'bar', 'kind': 'func', 'file': 'b.ts',
         'start_line': 1, 'end_line': 5, 'signature': 'function bar()', 'exported': True,
         'selection_score': 6.0, 'inbound_calls': 3, 'outbound_calls': 1},
    ]
    selector = IncrementalSelector(symbols, ['foo', 'bar'], {'bugfix'}, total_budget=100000)
    wave1 = selector.get_wave_symbols(0)
    assert selector.selected_count > 0

    expanded = selector.expand_symbol('b.ts::bar')
    if expanded:
        assert expanded['id'] == 'b.ts::bar'

    plan = selector.get_expansion_plan(max_items=10)
    assert len(plan) >= 0


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


# ===================== Learned Scorer =====================

def test_learned_scorer_extract_features():
    sym = {
        'name': 'validateToken', 'kind': 'func', 'file': 'auth.ts',
        'start_line': 10, 'end_line': 25,
        'signature': 'function validateToken(token: string): boolean',
        'exported': True, 'inbound_calls': 5, 'outbound_calls': 2,
        'named_imports': 3, 'rank': 0.8, 'pagerank': 0.6,
    }
    keywords = ['auth', 'token', 'validate']
    features = extract_features(sym, keywords)
    assert len(features) == 15
    assert features[0] >= 0  # task_score_norm
    assert features[6] == 1.0  # is_func
    assert features[9] == 1.0  # is_exported


def test_learned_scorer_empty():
    scorer = LearnedScorer()
    features = extract_features(
        {'name': 'foo', 'kind': 'var', 'file': 'x.ts', 'start_line': 1, 'end_line': 1,
         'signature': 'const foo = 1', 'exported': False, 'inbound_calls': 0,
         'outbound_calls': 0, 'named_imports': 0, 'rank': 0, 'pagerank': 0},
        ['test']
    )
    score = scorer.predict(features)
    assert score >= 0


def test_learned_scorer_train_and_predict():
    scorer = LearnedScorer()
    X = [[0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.1, 0.5, 0.3, 0.2],
         [0.8, 0.6, 0.4, 0.3, 0.1, 0.1, 1.0, 0.0, 0.0, 1.0, 0.0, 0.15, 0.8, 0.5, 0.3],
         [0.2, 0.1, 0.05, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.05, 0.2, 0.1, 0.1]]
    y = [0.3, 0.8, 0.1]
    scorer.train(X, y, num_boost_round=10)

    if scorer.model is not None:
        pred = scorer.predict(X[0])
        assert pred >= 0


# ===================== GNN Scorer =====================

def test_gnn_extract_node_features():
    sym = {
        'name': 'validateToken', 'kind': 'func', 'file': 'auth.ts',
        'start_line': 10, 'end_line': 25,
        'signature': 'function validateToken(token: string): boolean',
        'exported': True, 'inbound_calls': 5, 'outbound_calls': 2,
        'named_imports': 3, 'resolved_imports': 2, 'rank': 0.8, 'pagerank': 0.6,
    }
    features = extract_node_features(sym, ['auth', 'token'])
    assert len(features) == 16
    assert features[0] == 1.0  # is_func
    assert features[4] == 1.0  # is_exported


def test_gnn_build_adjacency_list():
    symbols = [
        {'id': 'a.ts::foo'},
        {'id': 'b.ts::bar'},
        {'id': 'c.ts::baz'},
    ]
    edges = [
        {'source': 'a.ts::foo', 'target': 'b.ts::bar'},
        {'source': 'b.ts::bar', 'target': 'c.ts::baz'},
    ]
    adj = build_adjacency_list(symbols, edges)
    assert len(adj) == 3
    assert 1 in adj[0]
    assert 2 in adj[1]


def test_gnn_initialization():
    gnn = SimpleGNN(input_dim=16, hidden_dim=64, output_dim=1)
    assert not gnn._initialized
    if HAS_NUMPY:
        gnn._init_weights()
        assert gnn._initialized
    else:
        gnn._init_weights()
        assert not gnn._initialized


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
    from argon.engine.keywords import extract_task_keywords
    keywords = extract_task_keywords("fix authentication bug")
    assert 'authentication' in keywords or 'auth' in keywords
    assert 'bug' in keywords


def test_keyword_extraction_synonyms():
    from argon.engine.keywords import extract_task_keywords
    keywords = extract_task_keywords("fix login issue")
    assert 'login' in keywords
    assert 'auth' in keywords or 'authenticate' in keywords


def test_keyword_extraction_empty():
    from argon.engine.keywords import extract_task_keywords
    keywords = extract_task_keywords("")
    assert keywords == []


# ===================== Domain Functions =====================

def test_detect_project_domain_ml_import():
    from argon.engine.domain import detect_project_domain_ml
    assert callable(detect_project_domain_ml)


def test_detect_project_domain_keywords_import():
    from argon.engine.domain import detect_project_domain
    assert callable(detect_project_domain)
