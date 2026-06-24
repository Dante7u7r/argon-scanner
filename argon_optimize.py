#!/usr/bin/env python3
"""
ARGON Benchmark Gate
====================
Runs the 33-case benchmark dataset against the production scorer and gates
on recall: hard floor + anti-regression vs a pinned baseline. Use --gate-init
to (re)write the baseline after intentional dataset or scoring changes.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from argon.engine.graph import ArgonEngine

# =========================================================================
# BENCHMARK DATASET LOADER
# =========================================================================

def load_benchmark_dataset(path: str = None) -> Dict[str, Any]:
    if path is None:
        path = os.path.join(ROOT, "tests", "fixtures", "benchmark_dataset.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
# GATE MODE (anti-regression on recall, no optimization)
# =========================================================================

DEFAULT_BASELINE_NAME = "benchmark_baseline.json"


def _aggregate_recall(
    engine: ArgonEngine,
    fixture_graphs: Dict[str, Dict],
    dataset: Dict[str, Any],
) -> Dict[str, Any]:
    """Run every case with the engine's production weights and aggregate recall."""
    results: List[Dict[str, Any]] = []
    for case in dataset["cases"]:
        fixture = case["fixture"]
        if fixture not in fixture_graphs:
            print(f"[!] Skipping {case['id']}: fixture {fixture} not built")
            continue
        graph = fixture_graphs[fixture]
        r = run_benchmark_case(engine, graph, case)
        r["fixture"] = fixture
        r["category"] = case.get("category", "unknown")
        results.append(r)

    by_fixture: Dict[str, List[float]] = {}
    by_category: Dict[str, List[float]] = {}
    for r in results:
        by_fixture.setdefault(r["fixture"], []).append(r["recall"])
        by_category.setdefault(r["category"], []).append(r["recall"])

    fixture_recall = {f: sum(v) / len(v) for f, v in by_fixture.items()}
    category_recall = {c: sum(v) / len(v) for c, v in by_category.items()}
    aggregate = sum(r["recall"] for r in results) / max(1, len(results))

    return {
        "case_count": len(results),
        "aggregate_recall": round(aggregate, 4),
        "fixture_recall": {f: round(r, 4) for f, r in sorted(fixture_recall.items())},
        "category_recall": {c: round(r, 4) for c, r in sorted(category_recall.items())},
        "cases": [
            {
                "id": r["case_id"],
                "fixture": r["fixture"],
                "category": r["category"],
                "recall": round(r["recall"], 4),
                "score": round(r["score"], 4),
            }
            for r in results
        ],
    }


def _baseline_path(explicit: str = None) -> str:
    if explicit:
        return explicit
    return os.path.join(ROOT, "tests", "fixtures", DEFAULT_BASELINE_NAME)


def _dataset_hash(dataset: Dict[str, Any]) -> str:
    import hashlib
    payload = json.dumps(dataset["cases"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def save_baseline(
    engine: ArgonEngine,
    fixture_graphs: Dict[str, Dict],
    dataset: Dict[str, Any],
    path: str = None,
) -> Dict[str, Any]:
    report = _aggregate_recall(engine, fixture_graphs, dataset)
    report["dataset_hash"] = _dataset_hash(dataset)
    report["dataset_version"] = dataset.get("version", 0)
    out = _baseline_path(path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[+] Baseline saved: {out}")
    print(f"    aggregate recall: {report['aggregate_recall']:.4f} over {report['case_count']} cases")
    return report


def run_gate(
    engine: ArgonEngine,
    fixture_graphs: Dict[str, Dict],
    dataset: Dict[str, Any],
    baseline_path: str = None,
    min_recall: float = 0.80,
    max_regression: float = 0.03,
    max_fixture_regression: float = 0.10,
) -> Tuple[bool, Dict[str, Any]]:
    current = _aggregate_recall(engine, fixture_graphs, dataset)
    agg = current["aggregate_recall"]

    passed = True
    violations: List[str] = []
    warnings: List[str] = []

    if agg < min_recall:
        passed = False
        violations.append(f"aggregate recall {agg:.4f} below hard floor {min_recall:.2f}")

    bp = _baseline_path(baseline_path)
    baseline = None
    if os.path.exists(bp):
        with open(bp, encoding="utf-8") as f:
            baseline = json.load(f)
        b_agg = baseline.get("aggregate_recall", 0.0)
        drop = round(b_agg - agg, 4)
        if drop > max_regression:
            passed = False
            violations.append(
                f"aggregate recall regressed {drop:.4f} > {max_regression} (baseline {b_agg:.4f} -> {agg:.4f})"
            )
        b_hash = baseline.get("dataset_hash")
        c_hash = _dataset_hash(dataset)
        if b_hash and b_hash != c_hash:
            warnings.append(
                f"dataset changed since baseline (baseline hash {b_hash} != current {c_hash}); "
                "regenerate baseline with --gate-init"
            )
        for fixture, recall in current["fixture_recall"].items():
            b_recall = baseline.get("fixture_recall", {}).get(fixture)
            if b_recall is not None:
                f_drop = round(b_recall - recall, 4)
                if f_drop > max_fixture_regression:
                    warnings.append(
                        f"fixture {fixture} recall dropped {f_drop:.4f} (baseline {b_recall:.4f} -> {recall:.4f})"
                    )
    else:
        warnings.append(f"no baseline at {bp}; run --gate-init first to enable anti-regression")

    current["passed"] = passed
    current["violations"] = violations
    current["warnings"] = warnings
    current["baseline_path"] = bp
    current["baseline_exists"] = baseline is not None
    return passed, current


def _print_gate_report(report: Dict[str, Any]) -> None:
    agg = report["aggregate_recall"]
    print(f"\n{'=' * 60}")
    print(f"GATE REPORT — {report['case_count']} cases")
    print(f"{'=' * 60}")
    print(f"Aggregate recall: {agg:.4f}")

    print("\nBy fixture:")
    for f, r in report["fixture_recall"].items():
        print(f"  {f:20s} {r:.4f}")
    print("\nBy category:")
    for c, r in report["category_recall"].items():
        print(f"  {c:20s} {r:.4f}")

    if report["warnings"]:
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  ! {w}")

    if report["violations"]:
        print(f"\nFAIL — violations ({len(report['violations'])}):")
        for v in report["violations"]:
            print(f"  x {v}")
    else:
        print("\nPASS — gate OK")
    print(f"{'=' * 60}")


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
    parser = argparse.ArgumentParser(description="ARGON Benchmark Gate — recall anti-regression on the 33-case dataset")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gate", action="store_true", default=True, help="Run recall gate against baseline (default mode). Exit 1 on regression.")
    mode.add_argument("--gate-init", action="store_true", help="Run all cases and save recall baseline. Use after intentional dataset/scoring changes.")
    parser.add_argument("--baseline", type=str, default=None, help=f"Baseline path (default: tests/fixtures/{DEFAULT_BASELINE_NAME})")
    parser.add_argument("--min-recall", type=float, default=0.80, help="Hard floor for aggregate recall (default: 0.80)")
    parser.add_argument("--max-regression", type=float, default=0.03, help="Max allowed aggregate recall drop vs baseline (default: 0.03)")
    parser.add_argument("--max-fixture-regression", type=float, default=0.10, help="Fixture recall drop that triggers a warning (default: 0.10)")
    parser.add_argument("--dataset", type=str, default=None, help="Dataset path")
    args = parser.parse_args()

    print("=" * 60)
    print("ARGON Benchmark Gate" + (" — INIT" if args.gate_init else ""))
    print("=" * 60)

    dataset = load_benchmark_dataset(args.dataset)
    print(f"[*] Loaded {len(dataset['cases'])} benchmark cases")

    fixture_graphs = build_fixture_graphs(dataset)
    engine = ArgonEngine(".", precision=True, model="gpt-4.1")

    # ---- gate-init: save baseline ----
    if args.gate_init:
        save_baseline(engine, fixture_graphs, dataset, path=args.baseline)
        return 0

    # ---- gate (default): anti-regression check ----
    passed, report = run_gate(
        engine, fixture_graphs, dataset,
        baseline_path=args.baseline,
        min_recall=args.min_recall,
        max_regression=args.max_regression,
        max_fixture_regression=args.max_fixture_regression,
    )
    _print_gate_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
