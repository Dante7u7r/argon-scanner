import json
from pathlib import Path

from argon import ArgonEngine
from argon_bench import score_graph
from argon_laravel import laravel_overview, laravel_routes, laravel_schema, laravel_recent_errors


def test_quality_benchmark_scores_expected_symbols(monorepo_project: Path):
    engine = ArgonEngine(str(monorepo_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    spec = {
        "task": "fix checkout total bug in tests",
        "expected_top_symbols": ["checkoutTotal", "sumPrice", "testCheckoutTotal"],
        "forbidden_top_symbols": ["GeneratedTypes", "Theme"],
        "max_tokens": 1200,
        "top_n": 10,
    }

    result = score_graph(graph, str(monorepo_project), spec)

    assert result["score"] >= 0.8
    assert result["budget_ok"] is True
    assert not result["forbidden_found"]


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
