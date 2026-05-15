import json
from pathlib import Path

from argon import ArgonEngine, TokenCounter


def test_precision_resolves_ts_alias_python_relative_imports_and_gitignore(universal_project: Path):
    engine = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()

    node_ids = {node["id"] for node in graph["nodes"]}
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}

    assert "ignored_assets/noise.ts" not in node_ids
    assert "scratch.tmp" not in node_ids
    assert ("ts/src/main.ts", "ts/src/core/helper.ts") in edges
    assert ("py/pkg/main.py", "py/pkg/helper.py") in edges
    assert graph["stats"]["unresolved_imports"] == 0
    assert graph["stats"]["total_symbols"] >= 5
    assert graph["stats"]["total_symbol_connections"] >= 2
    assert graph["stats"]["total_symbol_calls"] >= 1


def test_precision_context_json_respects_token_budget(universal_project: Path, tmp_path: Path):
    engine = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()
    output = tmp_path / "ARGON_PRECISION.json"

    engine.generate_precision_context(
        graph,
        str(output),
        task="fix helper runtime bug",
        max_tokens=900,
        output_format="json",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    counter = TokenCounter("gpt-4.1")

    assert payload["precision"] is True
    assert payload["used_tokens"] <= 900
    assert counter.count(output.read_text(encoding="utf-8")) <= 900
    assert payload["symbols"]
    assert any("helper" in symbol["name"].lower() for symbol in payload["symbols"])


def test_precision_selector_prefers_task_symbols_over_generic_fallback(universal_project: Path):
    engine = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()

    selected = engine._select_precision_symbols(graph, "fix python helper bug")
    selected_ids = [symbol["id"] for symbol in selected[:5]]

    assert any("py/pkg/helper.py::py_helper" == symbol_id for symbol_id in selected_ids)
    assert getattr(engine, "_last_selection_report")["direct_matches"] >= 1


def test_precision_handles_monorepo_alias_reexports_tests_and_python_absolute_imports(monorepo_project: Path):
    engine = ArgonEngine(str(monorepo_project), precision=True, model="gpt-4.1")
    graph = engine.build_graph()

    node_ids = {node["id"] for node in graph["nodes"]}
    edges = {(edge["source"], edge["target"], edge.get("kind")) for edge in graph["edges"]}

    assert "dist/bundle.ts" not in node_ids
    assert ("packages/app/src/checkout.ts", "packages/shared/src/index.ts", "import") in edges
    assert ("packages/shared/src/index.ts", "packages/shared/src/math.ts", "re-export") in edges
    assert any(
        source == "services/billing/billing/invoice.py"
        and target == "services/billing/billing/money.py"
        for source, target, _ in edges
    )
    assert graph["stats"]["unresolved_imports"] == 0

    selected = engine._select_precision_symbols(graph, "fix checkout total bug in tests")
    selected_ids = [symbol["id"] for symbol in selected[:8]]

    assert "packages/app/src/checkout.ts::checkoutTotal" in selected_ids
    assert any(symbol_id.endswith("checkout.test.ts::testCheckoutTotal") for symbol_id in selected_ids)


def test_precision_context_xml_and_markdown_do_not_exceed_budget(universal_project: Path, tmp_path: Path):
    counter = TokenCounter("gpt-4.1")

    for fmt, suffix in [("xml", "xml"), ("markdown", "md")]:
        engine = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1")
        graph = engine.build_graph()
        output = tmp_path / f"ARGON_PRECISION.{suffix}"

        engine.generate_precision_context(
            graph,
            str(output),
            task="fix helper runtime bug",
            max_tokens=900,
            output_format=fmt,
        )

        text = output.read_text(encoding="utf-8")
        assert counter.count(text) <= 900
        assert "helper" in text.lower()


def test_parse_cache_is_used_on_second_scan(universal_project: Path):
    first = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1").build_graph()
    second = ArgonEngine(str(universal_project), precision=True, model="gpt-4.1").build_graph()

    assert first["stats"]["cache_hits"] == 0
    assert second["stats"]["cache_hits"] >= first["stats"]["total_files"]
    assert ".argon_cache.json" not in {node["id"] for node in second["nodes"]}
