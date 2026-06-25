from pathlib import Path

from argon import ArgonEngine


def test_scope_tracking_local_calls(tmp_path: Path):
    project = tmp_path / "local_calls"
    project.mkdir()
    (project / "main.py").write_text(
        "def calculate_taxes(amount):\n"
        "    return amount * 0.16\n\n"
        "def process_checkout(cart):\n"
        "    total = sum(cart)\n"
        "    taxes = calculate_taxes(total)\n"
        "    return total + taxes\n",
        encoding="utf-8",
    )

    graph = ArgonEngine(str(project), precision=True, model="gpt-4.1").build_graph()
    calls = {
        (edge["source"], edge["target"])
        for edge in graph["symbol_edges"]
        if edge.get("kind") in {"calls-symbol", "calls-symbol-local"}
    }

    assert (
        "main.py::process_checkout",
        "main.py::calculate_taxes",
    ) in calls


def test_scope_tracking_cross_file_python(tmp_path: Path):
    project = tmp_path / "cross_file_py"
    project.mkdir()
    (project / "a.py").write_text(
        "def calculate_taxes(amount):\n"
        "    return amount * 0.16\n",
        encoding="utf-8",
    )
    (project / "b.py").write_text(
        "from a import calculate_taxes\n\n"
        "def process_checkout(cart):\n"
        "    total = sum(cart)\n"
        "    taxes = calculate_taxes(total)\n"
        "    return total + taxes\n",
        encoding="utf-8",
    )

    graph = ArgonEngine(str(project), precision=True, model="gpt-4.1").build_graph()
    calls = {
        (edge["source"], edge["target"])
        for edge in graph["symbol_edges"]
        if edge.get("kind") in {"calls-symbol", "calls-symbol-local"}
    }

    assert (
        "b.py::process_checkout",
        "a.py::calculate_taxes",
    ) in calls


def test_scope_tracking_cross_file_typescript(tmp_path: Path):
    import json

    project = tmp_path / "cross_file_ts"
    project.mkdir()
    (project / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": "."}}), encoding="utf-8"
    )
    src = project / "src"
    src.mkdir()
    (src / "math.ts").write_text(
        "export function sumPrice(a: number, b: number): number {\n"
        "  return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    (src / "checkout.ts").write_text(
        "import { sumPrice } from './math';\n\n"
        "export function checkoutTotal(items: number[]): number {\n"
        "  return items.reduce((total, item) => sumPrice(total, item), 0);\n"
        "}\n",
        encoding="utf-8",
    )

    graph = ArgonEngine(str(project), precision=True, model="gpt-4.1").build_graph()
    calls = {
        (edge["source"], edge["target"])
        for edge in graph["symbol_edges"]
        if edge.get("kind") in {"calls-symbol", "calls-symbol-local"}
    }

    assert (
        "src/checkout.ts::checkoutTotal",
        "src/math.ts::sumPrice",
    ) in calls
