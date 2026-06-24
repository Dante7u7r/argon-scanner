#!/usr/bin/env python3
"""Quality benchmarks for Argon Precision context retrieval.

The benchmark is intentionally centered on the product goal: can ARGON put
the symbols required for a task inside a strict token budget without dragging
in obvious noise?
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from argon import ArgonEngine, TokenCounter
from argon.utils.tokens import resolve_precision_budget


def _contains_any(symbol_id: str, needles: List[str]) -> bool:
    low = symbol_id.lower()
    return any(needle.lower() in low for needle in needles)


def _matches_required(symbol_id: str, required: str, exact: bool) -> bool:
    left = symbol_id.lower()
    right = required.lower()
    return left == right if exact else right in left


def _find_required(symbol_ids: List[str], required: List[str], exact: bool) -> List[str]:
    return [
        item
        for item in required
        if any(_matches_required(symbol_id, item, exact) for symbol_id in symbol_ids)
    ]


def _required_ranks(symbol_ids: List[str], required: List[str], exact: bool) -> Dict[str, Optional[int]]:
    ranks: Dict[str, Optional[int]] = {}
    for item in required:
        rank = None
        for index, symbol_id in enumerate(symbol_ids, start=1):
            if _matches_required(symbol_id, item, exact):
                rank = index
                break
        ranks[item] = rank
    return ranks


def _normalize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(spec)
    if "must_include_ids" in normalized and "expected_top_symbols" not in normalized:
        normalized["expected_top_symbols"] = normalized["must_include_ids"]
    if "must_include" in normalized and "expected_top_symbols" not in normalized:
        normalized["expected_top_symbols"] = normalized["must_include"]
    if "must_not_include_ids" in normalized and "forbidden_top_symbols" not in normalized:
        normalized["forbidden_top_symbols"] = normalized["must_not_include_ids"]
    if "must_not_include" in normalized and "forbidden_top_symbols" not in normalized:
        normalized["forbidden_top_symbols"] = normalized["must_not_include"]
    if "budget" in normalized and "max_tokens" not in normalized:
        normalized["max_tokens"] = normalized["budget"]
    return normalized


def _identifier_tokens(text: str) -> List[str]:
    import re
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[@./_\-:]+', ' ', text)
    return [p.lower() for p in re.findall(r'[A-Za-z0-9]+', text)]


def _task_tokens(task: str) -> List[str]:
    stop_words = {
        "the", "a", "an", "is", "are", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "and", "or", "not", "fix", "add", "update",
        "change", "when", "empty", "wrong", "support",
    }
    return list(dict.fromkeys(token for token in _identifier_tokens(task) if len(token) > 2 and token not in stop_words))


def _baseline_rankings(graph: Dict[str, Any], task: str) -> Dict[str, List[str]]:
    tokens = set(_task_tokens(task))
    symbols = list(graph.get("symbols", []))

    grep_ranked = []
    for sym in symbols:
        searchable = " ".join([
            sym.get("id", ""),
            sym.get("name", ""),
            sym.get("file", ""),
            sym.get("signature", ""),
        ])
        sym_tokens = set(_identifier_tokens(searchable))
        overlap = tokens & sym_tokens
        if not overlap:
            continue
        name_overlap = tokens & set(_identifier_tokens(sym.get("name", "")))
        file_overlap = tokens & set(_identifier_tokens(sym.get("file", "")))
        score = (len(name_overlap) * 3.0) + (len(file_overlap) * 1.2) + len(overlap)
        grep_ranked.append((score, float(sym.get("rank", 0)), sym.get("id", "")))
    grep_ranked.sort(reverse=True)

    pagerank_ranked = sorted(
        ((float(sym.get("rank", 0)), sym.get("id", "")) for sym in symbols),
        reverse=True,
    )

    return {
        "grep": [sid for _, _, sid in grep_ranked if sid],
        "pagerank": [sid for _, sid in pagerank_ranked if sid],
    }


def _score_symbol_ids(symbol_ids: List[str], required: List[str], exact: bool, top_n: int) -> Dict[str, Any]:
    top_ids = symbol_ids[:top_n]
    found = _find_required(top_ids, required, exact)
    ranks = _required_ranks(symbol_ids, required, exact)
    found_ranks = [rank for rank in ranks.values() if rank is not None]
    return {
        "recall_at_top": round(len(found) / max(1, len(required)), 4),
        "precision_at_top": round(min(1.0, len(found) / max(1, min(top_n, len(top_ids)))), 4),
        "required_ranks": ranks,
        "worst_required_rank": max(found_ranks) if found_ranks else None,
    }


def score_graph(graph: Dict[str, Any], root_dir: str, spec: Dict[str, Any], model: str = "gpt-4.1") -> Dict[str, Any]:
    spec = _normalize_spec(spec)
    engine = ArgonEngine(root_dir, precision=True, model=model)
    selected = engine._select_precision_symbols(graph, spec["task"], int(spec.get("max_tokens", 0)))
    top_n = int(spec.get("top_n", 10))
    all_ids = [sym["id"] for sym in selected]
    top_ids = [sym["id"] for sym in selected[:top_n]]
    critical_ids = [
        sym["id"]
        for sym in selected
        if sym.get("context_tier") in {"critical", "workflow"}
    ]

    exact_required = bool(spec.get("must_include_ids"))
    exact_forbidden = bool(spec.get("must_not_include_ids"))
    expected = spec.get("must_include_ids") or spec.get("expected_top_symbols", [])
    critical_expected = spec.get("must_include_critical_ids") or expected
    forbidden = spec.get("forbidden_top_symbols", [])
    found = _find_required(top_ids, expected, exact_required)
    critical_found = _find_required(critical_ids, critical_expected, exact_required)
    forbidden_found = [
        item
        for item in forbidden
        if any(_matches_required(symbol_id, item, exact_forbidden) for symbol_id in top_ids)
    ]
    ranks = _required_ranks(all_ids, expected, exact_required)
    missing = [item for item in expected if item not in found]
    first_missing = missing[0] if missing else None
    found_ranks = [rank for rank in ranks.values() if rank is not None]
    worst_required_rank = max(found_ranks) if found_ranks else None

    recall_at_budget = len(found) / max(1, len(expected))
    critical_recall = len(critical_found) / max(1, len(critical_expected))
    precision_at_top = min(1.0, len(found) / max(1, min(top_n, len(top_ids))))
    precision_at_critical = min(1.0, len(critical_found) / max(1, len(critical_ids) or len(top_ids)))
    forbidden_penalty = len(forbidden_found) / max(1, len(forbidden))
    unresolved = graph.get("stats", {}).get("unresolved_imports", 0)
    total_files = max(1, graph.get("stats", {}).get("total_files", 1))
    unresolved_ratio = unresolved / total_files

    context_tokens = None
    budget_ok = True
    context_audit: Dict[str, Any] = {
        "available": False,
        "budget_utilization": None,
        "context_required_recall": None,
        "critical_full_code_symbols": 0,
        "compact_symbols": 0,
        "support_compacted": 0,
        "expansion_plan_items": 0,
        "guardrails_ok": False,
    }
    max_tokens = spec.get("max_tokens")
    if max_tokens:
        out_path = os.path.join(root_dir, ".argon_bench_context.json")
        engine.generate_precision_context(
            graph,
            out_path,
            task=spec["task"],
            max_tokens=int(max_tokens),
            output_format="json",
            budget_profile=spec.get("budget_profile", "custom"),
        )
        text = Path(out_path).read_text(encoding="utf-8")
        context_tokens = TokenCounter(model).count(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        effective_max_tokens, _ = resolve_precision_budget(int(max_tokens), spec.get("budget_profile", "custom"))
        budget_ok = context_tokens <= effective_max_tokens
        context_symbol_ids = [sym.get("id", "") for sym in payload.get("symbols", [])]
        context_found = _find_required(context_symbol_ids, expected, exact_required)
        reachable_symbol_ids = list(dict.fromkeys(context_symbol_ids))
        reachable_found = _find_required(reachable_symbol_ids, expected, exact_required)
        full_code_symbols = [sym for sym in payload.get("symbols", []) if sym.get("code")]
        critical_full_code = [
            sym for sym in full_code_symbols
            if sym.get("tier") in {"critical", "workflow"}
        ]
        layers = {}
        for sym in payload.get("symbols", []):
            tier = sym.get("tier", "support")
            layers.setdefault(tier, []).append(sym.get("id", ""))
        context_audit = {
            "available": True,
            "budget_profile": spec.get("budget_profile", "custom"),
            "effective_max_tokens": effective_max_tokens,
            "budget_utilization": round(context_tokens / max(1, effective_max_tokens), 4),
            "context_required_recall": round(len(context_found) / max(1, len(expected)), 4),
            "required_reachable_recall": round(len(reachable_found) / max(1, len(expected)), 4),
            "required_in_context": context_found,
            "required_reachable": reachable_found,
            "critical_full_code_symbols": len(critical_full_code),
            "full_code_symbols": len(full_code_symbols),
            "compact_symbols": 0,
            "support_compacted": 0,
            "expansion_plan_items": 0,
            "has_critical_layer": bool(layers.get("critical")),
            "guardrails_ok": (
                budget_ok
                and bool(layers.get("critical"))
                and len(critical_full_code) > 0
                and len(reachable_found) == len(expected)
            ),
        }
        try:
            os.remove(out_path)
        except OSError:
            pass
    tokens_per_required_symbol = (
        round(context_tokens / max(1, len(found)), 2)
        if context_tokens is not None
        else None
    )
    baselines = {
        name: _score_symbol_ids(ids, expected, exact_required, top_n)
        for name, ids in _baseline_rankings(graph, spec["task"]).items()
    }
    best_baseline_recall = max((item["recall_at_top"] for item in baselines.values()), default=0.0)
    best_baseline_precision = max((item["precision_at_top"] for item in baselines.values()), default=0.0)
    recall_lift_vs_best_baseline = round(recall_at_budget - best_baseline_recall, 4)
    precision_lift_vs_best_baseline = round(precision_at_top - best_baseline_precision, 4)

    score = (
        (recall_at_budget * 0.55)
        + (critical_recall * 0.15)
        + (precision_at_critical * 0.12)
        + ((1 - forbidden_penalty) * 0.10)
        + ((1 - min(unresolved_ratio, 1)) * 0.08)
    )
    if not budget_ok:
        score *= 0.75

    return {
        "task": spec["task"],
        "score": round(score, 4),
        "recall_at_budget": round(recall_at_budget, 4),
        "critical_recall": round(critical_recall, 4),
        "precision_at_top": round(precision_at_top, 4),
        "precision_at_critical": round(precision_at_critical, 4),
        "top_symbols": top_ids,
        "critical_symbols": critical_ids,
        "critical_expected": critical_expected,
        "critical_found": critical_found,
        "required_ranks": ranks,
        "first_missing_required": first_missing,
        "worst_required_rank": worst_required_rank,
        "expected_found": found,
        "expected_missing": missing,
        "forbidden_found": forbidden_found,
        "unresolved_ratio": round(unresolved_ratio, 4),
        "budget_ok": budget_ok,
        "context_tokens": context_tokens,
        "context_audit": context_audit,
        "tokens_per_required_symbol": tokens_per_required_symbol,
        "baselines": baselines,
        "recall_lift_vs_best_baseline": recall_lift_vs_best_baseline,
        "precision_lift_vs_best_baseline": precision_lift_vs_best_baseline,
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
