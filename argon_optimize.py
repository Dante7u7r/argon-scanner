#!/usr/bin/env python3
"""
ARGON Benchmark Optimizer
=========================
Uses coordinate descent to optimize scoring weights against the benchmark dataset.
"""

import json
import os
import sys
import math
import copy
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from argon.engine.graph import ArgonEngine, _pagerank


# =========================================================================
# BENCHMARK DATASET LOADER
# =========================================================================

def load_benchmark_dataset(path: str = None) -> Dict[str, Any]:
    if path is None:
        path = os.path.join(ROOT, "tests", "fixtures", "benchmark_dataset.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_benchmarks() -> Dict[str, Any]:
    path = os.path.join(ROOT, "tests", "fixtures", "benchmark_results.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# =========================================================================
# SCORING METRICS
# =========================================================================

def recall_at_k(expected: List[str], found_ids: List[str], k: int = None) -> float:
    if not expected:
        return 1.0
    search_ids = found_ids[:k] if k else found_ids
    search_set = {s.lower() for s in search_ids}
    matched = sum(1 for e in expected if any(e.lower() in s for s in search_set))
    return matched / len(expected)


def precision_at_k(expected: List[str], found_ids: List[str], k: int) -> float:
    if k == 0 or not expected:
        return 0.0
    top_k = found_ids[:k]
    top_set = {s.lower() for s in top_k}
    matched = sum(1 for e in expected if any(e.lower() in s for s in top_set))
    return min(1.0, matched / k)


def forbidden_penalty(forbidden: List[str], found_ids: List[str]) -> float:
    if not forbidden:
        return 0.0
    top_set = {s.lower() for s in found_ids}
    found = sum(1 for f in forbidden if any(f.lower() in s for s in top_set))
    return found / len(forbidden)


def tier_accuracy(expected_tier: Dict[str, List[str]], selected: List[Dict]) -> float:
    if not expected_tier:
        return 1.0
    total = 0
    correct = 0
    for tier, symbols in expected_tier.items():
        for sym_name in symbols:
            total += 1
            for s in selected:
                if sym_name.lower() in s.get("id", "").lower():
                    if s.get("context_tier") == tier:
                        correct += 1
                    break
    return correct / total if total > 0 else 1.0


# =========================================================================
# BENCHMARK RUNNER
# =========================================================================

def run_benchmark_case(
    engine: ArgonEngine,
    graph: Dict[str, Any],
    case: Dict[str, Any],
) -> Dict[str, Any]:
    task = case["task"]
    budget = case.get("budget", 4000)
    top_n = case.get("top_n", 10)
    must_include = case.get("must_include", [])
    must_not_include = case.get("must_not_include", [])
    expected_tier = case.get("expected_tier", {})

    selected = engine._select_precision_symbols(graph, task)
    all_ids = [s["id"] for s in selected]
    top_ids = [s["id"] for s in selected[:top_n]]

    recall = recall_at_k(must_include, all_ids)
    precision = precision_at_k(must_include, all_ids, top_n)
    penalty = forbidden_penalty(must_not_include, all_ids)
    tier_acc = tier_accuracy(expected_tier, selected)

    score = (recall * 0.40 + precision * 0.25 + (1 - penalty) * 0.20 + tier_acc * 0.15)

    return {
        "case_id": case["id"],
        "task": task,
        "recall": recall,
        "precision": precision,
        "forbidden_penalty": penalty,
        "tier_accuracy": tier_acc,
        "score": score,
        "selected_count": len(selected),
        "top_ids": top_ids[:top_n],
    }


# =========================================================================
# WEIGHT OPTIMIZATION (Coordinate Descent)
# =========================================================================

DEFAULT_WEIGHTS = {
    "name_weight": 5.0,
    "file_weight": 1.6,
    "signature_weight": 1.5,
    "overlap_weight": 0.6,
    "focus_bonus": 1.2,
    "keyword_name_bonus": 1.5,
    "keyword_file_bonus": 0.45,
    "task_ratio": 0.55,
    "call_ratio": 0.25,
    "graph_ratio": 0.20,
    "import_neighbor_factor": 0.35,
    "callee_factor": 0.65,
    "caller_factor": 0.70,
    "generic_penalty": 0.45,
    "support_factor_tests": 0.55,
    "support_factor_model": 0.25,
    "support_factor_no_focus": 0.58,
    "pagerank_precision_weight": 0.7,
    "connections_precision_weight": 0.2,
    "symbols_precision_weight": 0.1,
}


def apply_weights_to_engine(engine: ArgonEngine, weights: Dict[str, float]) -> None:
    engine._weights = weights


def objective_function(
    engine: ArgonEngine,
    fixture_graphs: Dict[str, Dict],
    dataset: Dict[str, Any],
    weights: Dict[str, float],
) -> float:
    apply_weights_to_engine(engine, weights)
    total_score = 0.0
    total_cases = 0

    for case in dataset["cases"]:
        fixture = case["fixture"]
        if fixture not in fixture_graphs:
            continue
        graph = fixture_graphs[fixture]
        result = run_benchmark_case(engine, graph, case)
        total_score += result["score"]
        total_cases += 1

    return total_score / max(1, total_cases)


def coordinate_descent(
    engine: ArgonEngine,
    fixture_graphs: Dict[str, Dict],
    dataset: Dict[str, Any],
    initial_weights: Dict[str, float] = None,
    max_iterations: int = 50,
    learning_rate: float = 0.1,
    patience: int = 10,
) -> Tuple[Dict[str, float], List[float]]:
    weights = dict(initial_weights or DEFAULT_WEIGHTS)
    best_score = objective_function(engine, fixture_graphs, dataset, weights)
    best_weights = dict(weights)
    history = [best_score]
    no_improve_count = 0

    print(f"[*] Initial score: {best_score:.4f}")

    for iteration in range(max_iterations):
        improved = False
        for key in weights:
            for delta in [learning_rate, -learning_rate]:
                new_weights = dict(weights)
                new_weights[key] = max(0.01, weights[key] + delta)
                new_score = objective_function(engine, fixture_graphs, dataset, new_weights)
                if new_score > best_score:
                    best_score = new_score
                    best_weights = dict(new_weights)
                    weights = dict(new_weights)
                    improved = True
                    no_improve_count = 0
                    break
            if not improved:
                no_improve_count += 1

        history.append(best_score)
        if iteration % 5 == 0:
            print(f"  [{iteration:3d}] score: {best_score:.4f}")

        if no_improve_count >= patience * len(weights):
            print(f"  Converged at iteration {iteration}")
            break

    return best_weights, history


# =========================================================================
# MAIN
# =========================================================================

def build_fixture_graphs(dataset: Dict[str, Any]) -> Dict[str, Dict]:
    fixture_dirs = {
        "fixture_ts": os.path.join(ROOT, "tests", "fixtures", "fixture_ts"),
        "fixture_python": os.path.join(ROOT, "tests", "fixtures", "fixture_python"),
        "fixture_java": os.path.join(ROOT, "tests", "fixtures", "fixture_java"),
        "fixture_csharp": os.path.join(ROOT, "tests", "fixtures", "fixture_csharp"),
        "fixture_fastapi": os.path.join(ROOT, "tests", "fixtures", "fixture_fastapi"),
    }

    graphs = {}
    for fixture_name, fixture_path in fixture_dirs.items():
        if not os.path.exists(fixture_path):
            print(f"[!] Fixture not found: {fixture_path}")
            continue
        print(f"[*] Building graph for {fixture_name}...")
        engine = ArgonEngine(fixture_path, precision=True, model="gpt-4.1")
        graph = engine.build_graph()
        graphs[fixture_name] = graph
        print(f"    Files: {graph['stats']['total_files']}, Symbols: {graph['stats']['total_symbols']}")

    return graphs


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ARGON Benchmark Optimizer")
    parser.add_argument("--iterations", type=int, default=50, help="Max iterations")
    parser.add_argument("--lr", type=float, default=0.1, help="Learning rate")
    parser.add_argument("--dataset", type=str, default=None, help="Dataset path")
    parser.add_argument("--output", type=str, default="optimized_weights.json")
    args = parser.parse_args()

    print("=" * 60)
    print("ARGON Benchmark Optimizer")
    print("=" * 60)

    dataset = load_benchmark_dataset(args.dataset)
    print(f"[*] Loaded {len(dataset['cases'])} benchmark cases")

    fixture_graphs = build_fixture_graphs(dataset)

    engine = ArgonEngine(".", precision=True, model="gpt-4.1")

    print("\n[*] Running optimization...")
    optimized_weights, history = coordinate_descent(
        engine, fixture_graphs, dataset,
        max_iterations=args.iterations,
        learning_rate=args.lr,
    )

    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    print(f"Initial score: {history[0]:.4f}")
    print(f"Final score:   {history[-1]:.4f}")
    print(f"Improvement:   {history[-1] - history[0]:.4f}")

    print(f"\nOptimized weights:")
    for key, value in sorted(optimized_weights.items()):
        default = DEFAULT_WEIGHTS.get(key, 0)
        delta = value - default
        if abs(delta) > 0.01:
            print(f"  {key}: {default:.3f} -> {value:.3f} ({delta:+.3f})")
        else:
            print(f"  {key}: {value:.3f}")

    output_path = os.path.join(ROOT, args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "weights": optimized_weights,
            "history": history,
            "initial_score": history[0],
            "final_score": history[-1],
        }, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Weights saved to {output_path}")

    print("\n[*] Running final benchmark with optimized weights...")
    apply_weights_to_engine(engine, optimized_weights)
    for case in dataset["cases"]:
        fixture = case["fixture"]
        if fixture not in fixture_graphs:
            continue
        graph = fixture_graphs[fixture]
        result = run_benchmark_case(engine, graph, case)
        status = "OK" if result["score"] >= 0.8 else "WARN"
        print(f"  [{status}] {result['case_id']}: {result['score']:.3f} (recall={result['recall']:.2f}, prec={result['precision']:.2f})")


if __name__ == "__main__":
    main()
