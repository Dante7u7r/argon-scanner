import json
from pathlib import Path

from argon import ArgonEngine
from argon_bench import score_graph
from argon_laravel import laravel_overview, laravel_recent_errors, laravel_routes, laravel_schema
from argon_quality_bench import (
    BENCHMARK_SPECS,
    create_fixture_python,
    create_fixture_typescript,
    create_fixture_typescript_noisy,
)


def test_quality_benchmark_scores_expected_symbols(monorepo_project: Path):
    engine = ArgonEngine(str(monorepo_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = {
        "task": "fix checkout total bug in tests",
        "must_include_ids": [
            "packages/app/src/checkout.ts::checkoutTotal",
            "packages/shared/src/math.ts::sumPrice",
            "packages/app/src/checkout.test.ts::testCheckoutTotal",
        ],
        "must_include_critical_ids": [
            "packages/app/src/checkout.ts::checkoutTotal",
            "packages/shared/src/math.ts::sumPrice",
            "packages/app/src/checkout.test.ts::testCheckoutTotal",
        ],
        "expected_top_symbols": ["checkoutTotal", "sumPrice", "testCheckoutTotal"],
        "forbidden_top_symbols": ["GeneratedTypes", "Theme"],
        "max_tokens": 1200,
        "top_n": 10,
    }

    result = score_graph(graph, str(monorepo_project), spec)

    assert result["score"] >= 0.7
    assert result["recall_at_budget"] == 1.0
    assert result["critical_recall"] == 1.0
    assert result["first_missing_required"] is None
    assert result["tokens_per_required_symbol"] is not None
    assert result["precision_at_top"] > 0
    assert "grep" in result["baselines"]
    assert "pagerank" in result["baselines"]
    assert result["recall_lift_vs_best_baseline"] >= 0
    assert result["context_audit"]["expansion_plan_items"] >= 0
    assert not result["forbidden_found"]


def test_quality_benchmark_audits_effective_budget_profile(universal_project: Path):
    engine = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = {
        "task": "fix helper bug",
        "must_include_ids": ["ts/src/core/helper.ts::helper"],
        "must_include_critical_ids": ["ts/src/core/helper.ts::helper"],
        "max_tokens": 9000,
        "budget_profile": "micro",
        "top_n": 5,
    }

    result = score_graph(graph, str(universal_project), spec)

    assert result["budget_ok"] is True
    assert result["context_audit"]["budget_profile"] == "micro"
    assert result["context_audit"]["effective_max_tokens"] == 1500
    assert result["context_audit"]["budget_utilization"] <= 1.0


def test_auth_benchmark_keeps_order_math_out_of_top_context(tmp_path: Path):
    project = create_fixture_typescript(tmp_path)
    engine = ArgonEngine(str(project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = BENCHMARK_SPECS["fixture_ts"][0]

    result = score_graph(graph, str(project), spec)

    assert result["recall_at_budget"] == 1.0
    critical_set = set(result["critical_symbols"])
    required = {
        "src/services/userService.ts::loginUser",
        "src/lib/auth.ts::validateToken",
        "src/models/user.ts::User",
        "src/models/user.ts::createUser",
        "src/services/userService.ts::checkSession",
        "src/lib/auth.ts::authenticate",
    }
    assert required.issubset(critical_set)
    assert result["precision_at_critical"] >= 0.5
    assert "calculateTotal" not in result["forbidden_found"]
    assert not any("calculateTotal" in symbol for symbol in result["top_symbols"][: spec["top_n"]])


def test_refund_context_prioritizes_flow_before_models(tmp_path: Path):
    project = create_fixture_typescript(tmp_path)
    engine = ArgonEngine(str(project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = BENCHMARK_SPECS["fixture_ts"][1]

    result = score_graph(graph, str(project), spec)

    assert result["recall_at_budget"] == 1.0
    critical_set = set(result["critical_symbols"])
    required = {
        "src/lib/payment.ts::refundPayment",
        "src/services/orderService.ts::cancelOrder",
        "src/lib/payment.ts::processPayment",
        "src/services/orderService.ts::placeOrder",
    }
    assert required.issubset(critical_set)
    assert result["precision_at_critical"] >= 0.6


def test_noisy_typescript_context_beats_textual_baselines(tmp_path: Path):
    project = create_fixture_typescript_noisy(tmp_path)
    engine = ArgonEngine(str(project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = BENCHMARK_SPECS["fixture_ts_noisy"][0]

    result = score_graph(graph, str(project), spec)

    assert result["recall_at_budget"] == 1.0
    assert result["critical_recall"] == 1.0
    assert result["forbidden_found"] == []
    assert result["baselines"]["grep"]["recall_at_top"] < result["recall_at_budget"]
    assert result["precision_lift_vs_best_baseline"] > 0
    assert result["selection_report"]["isolated_focus_matches_filtered"] >= 1


def test_python_auth_context_filters_file_only_auth_noise(tmp_path: Path):
    project = create_fixture_python(tmp_path)
    engine = ArgonEngine(str(project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = BENCHMARK_SPECS["fixture_python"][0]

    result = score_graph(graph, str(project), spec)

    assert result["recall_at_budget"] == 1.0
    assert result["precision_at_top"] >= 0.5
    assert not any("hash_password" in symbol for symbol in result["top_symbols"])


def test_python_order_context_filters_call_expression_symbols(tmp_path: Path):
    project = create_fixture_python(tmp_path)
    engine = ArgonEngine(str(project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = BENCHMARK_SPECS["fixture_python"][1]

    result = score_graph(graph, str(project), spec)

    assert result["recall_at_budget"] == 1.0
    assert result["precision_at_top"] >= 0.6
    assert result["selection_report"]["noise_symbols_filtered"] >= 1
    assert not any("order_service.py::cache_set" in symbol for symbol in result["top_symbols"])


def test_laravel_adapter_reads_routes_schema_logs(laravel_project: Path):
    overview = laravel_overview(str(laravel_project))
    routes = laravel_routes(str(laravel_project))
    schema = laravel_schema(str(laravel_project))
    errors = laravel_recent_errors(str(laravel_project))

    assert overview["detected"] is True
    assert overview["laravel_version"] == "^12.0"
    assert routes[0]["uri"] == "/orders/{order}"
    assert "OrderController" in routes[0]["controllers"][0]
    assert schema[0]["tables"] == ["orders"]
    assert {"type": "string", "name": "status"} in schema[0]["columns"]
    assert "Order failure" in errors["lines"][0]


def test_precision_resolves_composer_psr4_php_imports(laravel_project: Path):
    engine = ArgonEngine(str(laravel_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}

    assert (
        "app/Http/Controllers/OrderController.php",
        "app/Models/Order.php",
    ) in edges
    assert graph["stats"]["unresolved_imports"] == 0
