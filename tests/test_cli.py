import json
from pathlib import Path

from conftest import run_argon


def test_cli_precision_writes_graph_context_and_view(universal_project: Path, tmp_path: Path):
    result = run_argon(
        universal_project,
        tmp_path,
        "--precision",
        "--task",
        "fix helper bug",
        "--budget",
        "1200",
        "--format",
        "json",
        "--view",
    )

    assert result.returncode == 0, result.stderr + result.stdout

    graph_path = tmp_path / "argon_graph.json"
    context_path = tmp_path / "ARGON_PRECISION.json"
    view_path = tmp_path / "argon_view.html"

    assert graph_path.exists()
    assert context_path.exists()
    assert view_path.exists()

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))

    assert graph["precision"] is True
    assert graph["stats"]["unresolved_imports"] == 0
    assert graph["stats"]["total_symbol_calls"] >= 1
    assert context["used_tokens"] <= 1200
    assert "ARGON_OS" in view_path.read_text(encoding="utf-8")


def test_cli_precision_budget_profile(universal_project: Path, tmp_path: Path):
    result = run_argon(
        universal_project,
        tmp_path,
        "--precision",
        "--task",
        "fix helper bug",
        "--budget",
        "9000",
        "--budget-profile",
        "micro",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    context = json.loads((tmp_path / "ARGON_PRECISION.json").read_text(encoding="utf-8"))
    assert context["budget_profile"] == "micro"
    assert context["max_tokens"] == 1500
    assert context["used_tokens"] <= 1500


def test_cli_precision_writes_xml_and_markdown_formats(universal_project: Path, tmp_path: Path):
    for fmt, filename, marker in [
        ("xml", "ARGON_PRECISION.xml", "<repository"),
        ("markdown", "ARGON_PRECISION.md", "# ARGON PRECISION CONTEXT"),
    ]:
        output = tmp_path / fmt
        output.mkdir()
        result = run_argon(
            universal_project,
            output,
            "--precision",
            "--task",
            "fix helper bug",
            "--budget",
            "1200",
            "--format",
            fmt,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        text = (output / filename).read_text(encoding="utf-8")
        assert marker in text
        assert "helper" in text.lower()


def test_cli_classic_context_still_works(universal_project: Path, tmp_path: Path):
    result = run_argon(universal_project, tmp_path, "--context", "--budget", "1200")

    assert result.returncode == 0, result.stderr + result.stdout
    assert (tmp_path / "argon_graph.json").exists()
    assert (tmp_path / "ARGON.md").exists()

    graph = json.loads((tmp_path / "argon_graph.json").read_text(encoding="utf-8"))
    assert graph["precision"] is False
    assert "ARGON PROJECT CONTEXT" in (tmp_path / "ARGON.md").read_text(encoding="utf-8")
