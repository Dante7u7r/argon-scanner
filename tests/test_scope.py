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