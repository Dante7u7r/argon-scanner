#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quality benchmarks for Argon Precision selection."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from argon import ArgonEngine, TokenCounter


def _contains_any(symbol_id: str, needles: List[str]) -> bool:
    low = symbol_id.lower()
    return any(needle.lower() in low for needle in needles)


def score_graph(graph: Dict[str, Any], root_dir: str, spec: Dict[str, Any], model: str = "gpt-4.1") -> Dict[str, Any]:
    engine = ArgonEngine(root_dir, precision=True, model=model)
    selected = engine._select_precision_symbols(graph, spec["task"])
    top_n = int(spec.get("top_n", 10))
    top_ids = [sym["id"] for sym in selected[:top_n]]

    expected = spec.get("expected_top_symbols", [])
    forbidden = spec.get("forbidden_top_symbols", [])
    found = [item for item in expected if _contains_any(" ".join(top_ids), [item])]
    forbidden_found = [item for item in forbidden if _contains_any(" ".join(top_ids), [item])]

    expected_score = len(found) / max(1, len(expected))
    forbidden_penalty = len(forbidden_found) / max(1, len(forbidden))
    unresolved = graph.get("stats", {}).get("unresolved_imports", 0)
    total_files = max(1, graph.get("stats", {}).get("total_files", 1))
    unresolved_ratio = unresolved / total_files

    context_tokens = None
    budget_ok = True
    max_tokens = spec.get("max_tokens")
    if max_tokens:
        out_path = os.path.join(root_dir, ".argon_bench_context.json")
        engine.generate_precision_context(
            graph,
            out_path,
            task=spec["task"],
            max_tokens=int(max_tokens),
            output_format="json",
        )
        text = Path(out_path).read_text(encoding="utf-8")
        context_tokens = TokenCounter(model).count(text)
        budget_ok = context_tokens <= int(max_tokens)
        try:
            os.remove(out_path)
        except OSError:
            pass

    score = (expected_score * 0.75) + ((1 - forbidden_penalty) * 0.15) + ((1 - min(unresolved_ratio, 1)) * 0.10)
    if not budget_ok:
        score *= 0.75

    return {
        "task": spec["task"],
        "score": round(score, 4),
        "top_symbols": top_ids,
        "expected_found": found,
        "expected_missing": [item for item in expected if item not in found],
        "forbidden_found": forbidden_found,
        "unresolved_ratio": round(unresolved_ratio, 4),
        "budget_ok": budget_ok,
        "context_tokens": context_tokens,
        "selection_report": getattr(engine, "_last_selection_report", {}),
    }


def run_benchmark(root_dir: str, spec_path: str, model: str = "gpt-4.1") -> Dict[str, Any]:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    engine = ArgonEngine(root_dir, precision=True, model=model)
    graph = engine.build_graph()
    cases = spec.get("cases", [spec])
    results = [score_graph(graph, root_dir, case, model=model) for case in cases]
    avg = sum(item["score"] for item in results) / max(1, len(results))
    return {
        "project": os.path.basename(os.path.abspath(root_dir)),
        "average_score": round(avg, 4),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ARGON quality benchmark runner")
    parser.add_argument("path", help="Project path")
    parser.add_argument("spec", help="Benchmark JSON spec")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--min-score", type=float, default=0.8)
    args = parser.parse_args()

    result = run_benchmark(os.path.abspath(args.path), os.path.abspath(args.spec), model=args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["average_score"] >= args.min_score else 1


if __name__ == "__main__":
    sys.exit(main())
