#!/usr/bin/env python3
"""
ARGON END-TO-END BENCHMARK v1.0
-------------------------------
Measures agent task completion quality with and without ARGON context.
Simulates an AI agent using the provided context to solve programming tasks.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argon import ArgonEngine
from argon_bench import score_graph
from argon_quality_bench import (
    BENCHMARK_SPECS,
    create_fixture_csharp,
    create_fixture_java,
    create_fixture_python,
    create_fixture_typescript,
    create_fixture_typescript_noisy,
)

E2E_CASES = [
    {
        "id": "ts_auth",
        "task": "fix authentication bug",
        "required_knowledge": [
            "User authentication",
            "Token validation",
            "Session management",
        ],
        "files_to_edit": [
            "userService",
            "auth",
        ],
        "forbidden_files": [
            "cache",  # unrelated to auth
        ],
        "min_required_symbols": 4,
        "max_context_tokens": 1500,
    },
    {
        "id": "ts_refund",
        "task": "add refund support for orders",
        "required_knowledge": [
            "Order processing",
            "Payment handling",
            "Refund calculation",
        ],
        "files_to_edit": [
            "order",
            "orderService",
        ],
        "forbidden_files": [],
        "min_required_symbols": 4,
        "max_context_tokens": 1500,
    },
    {
        "id": "py_auth",
        "task": "fix user authentication",
        "required_knowledge": [
            "authenticate",
            "user model",
            "token validate",
        ],
        "files_to_edit": [
            "auth_service",
            "user",
        ],
        "forbidden_files": [],
        "min_required_symbols": 4,
        "max_context_tokens": 1500,
    },
    {
        "id": "py_order",
        "task": "fix order placement with wrong total",
        "required_knowledge": [
            "order_service",
            "order model",
            "calculate",
        ],
        "files_to_edit": [
            "order_service",
            "order",
        ],
        "forbidden_files": [],
        "min_required_symbols": 4,
        "max_context_tokens": 1500,
    },
]


class AgentSimulator:
    def __init__(self, task: str, required_knowledge: List[str], files_to_edit: List[str]):
        self.task = task
        self.required_knowledge = required_knowledge
        self.files_to_edit = files_to_edit

    def evaluate_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        symbols = context.get('symbols', [])
        symbol_names = [s.get('name', '') for s in symbols]
        symbol_files = [s.get('file', '') for s in symbols]
        tiers = [s.get('context_tier', 'support') for s in symbols]
        snippet_count = sum(1 for s in symbols if s.get('code') or s.get('_snippet'))

        knowledge_covered = 0
        for knowledge in self.required_knowledge:
            knowledge_tokens = set(knowledge.lower().split())
            matched = False
            for sym in symbols:
                sym_text = (
                    sym.get('name', '') + ' ' +
                    sym.get('signature', '') + ' ' +
                    sym.get('id', '')
                ).lower()
                sym_words = set(sym_text.split())
                overlap = knowledge_tokens & sym_words
                partial_checks = 0
                for kt in knowledge_tokens:
                    for sw in sym_words:
                        if len(kt) >= 4 and len(sw) >= 4 and (kt in sw or sw in kt):
                            partial_checks += 1
                            break
                if len(overlap) >= 1 or partial_checks >= len(knowledge_tokens) * 0.5:
                    matched = True
                    break
            if matched:
                knowledge_covered += 1

        files_covered = 0
        for target_file in self.files_to_edit:
            for sym_file in symbol_files:
                if target_file.lower() in sym_file.lower():
                    files_covered += 1
                    break

        critical_count = sum(1 for t in tiers if t == 'critical')
        workflow_count = sum(1 for t in tiers if t == 'workflow')

        tokens_used = context.get('used_tokens', 0)
        budget = context.get('max_tokens', 0)
        token_efficiency = (
            1.0 - (tokens_used / max(budget, 1))
        ) if budget > 0 else 0

        knowledge_coverage = knowledge_covered / max(len(self.required_knowledge), 1)
        file_coverage = files_covered / max(len(self.files_to_edit), 1)

        quality_score = (
            knowledge_coverage * 0.45 +
            file_coverage * 0.25 +
            (critical_count / max(len(symbols), 1)) * 0.15 +
            token_efficiency * 0.15
        )

        return {
            'knowledge_coverage': round(knowledge_coverage, 3),
            'file_coverage': round(file_coverage, 3),
            'symbols_count': len(symbols),
            'critical_symbols': critical_count,
            'workflow_symbols': workflow_count,
            'snippets_provided': snippet_count,
            'tokens_used': tokens_used,
            'token_efficiency': round(token_efficiency, 3),
            'quality_score': round(quality_score, 3),
        }


def build_context_from_selection(project: Path, task: str, max_tokens: int) -> Dict[str, Any]:
    engine = ArgonEngine(str(project), precision=True, model='gpt-4.1')
    graph = engine.build_graph()

    from argon.engine.selector import select_precision_symbols
    selected, _report = select_precision_symbols(
        graph, task, max_tokens,
        false_positive_blacklist=engine.false_positive_blacklist,
        token_counter=engine.token_counter,
        read_snippet_fn=(engine.root, engine.parser),
    )

    layers = {'critical': [], 'workflow': [], 'support': []}
    for sym in selected:
        tier = sym.get('context_tier', 'support')
        if tier in layers:
            layers[tier].append(sym)

    used = sum(
        engine.token_counter.count(json.dumps(s, ensure_ascii=False))
        for s in selected
    )

    return {
        'symbols': selected,
        'layers': layers,
        'used_tokens': used,
        'max_tokens': max_tokens,
    }


def run_e2e_benchmark() -> Dict[str, Any]:
    import tempfile

    FIXTURE_BUILDERS = {
        'fixture_ts': create_fixture_typescript,
        'fixture_ts_noisy': create_fixture_typescript_noisy,
        'fixture_python': create_fixture_python,
        'fixture_java': create_fixture_java,
        'fixture_csharp': create_fixture_csharp,
    }

    results = []
    fixture_map = {
        'ts_auth': 'fixture_ts',
        'ts_refund': 'fixture_ts',
        'py_auth': 'fixture_python',
        'py_order': 'fixture_python',
    }

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        fixtures_built = {}

        for case in E2E_CASES:
            fixture_name = fixture_map[case['id']]
            if fixture_name not in fixtures_built:
                builder = FIXTURE_BUILDERS[fixture_name]
                project = builder(base)
                fixtures_built[fixture_name] = project
            else:
                project = fixtures_built[fixture_name]

            agent = AgentSimulator(
                task=case['task'],
                required_knowledge=case['required_knowledge'],
                files_to_edit=case['files_to_edit'],
            )

            context = build_context_from_selection(
                project, case['task'], case['max_context_tokens'],
            )

            eval_result = agent.evaluate_context(context)

            result = {
                'case_id': case['id'],
                'task': case['task'],
                'quality_score': eval_result['quality_score'],
                'knowledge_coverage': eval_result['knowledge_coverage'],
                'file_coverage': eval_result['file_coverage'],
                'symbols_count': eval_result['symbols_count'],
                'critical_symbols': eval_result['critical_symbols'],
                'tokens_used': eval_result['tokens_used'],
                'token_efficiency': eval_result['token_efficiency'],
            }
            results.append(result)

    avg_quality = sum(r['quality_score'] for r in results) / max(len(results), 1)
    avg_knowledge = sum(r['knowledge_coverage'] for r in results) / max(len(results), 1)
    avg_file = sum(r['file_coverage'] for r in results) / max(len(results), 1)
    avg_efficiency = sum(r['token_efficiency'] for r in results) / max(len(results), 1)
    avg_tokens = sum(r['tokens_used'] for r in results) / max(len(results), 1)

    return {
        'benchmark': 'argon_e2e_v1',
        'cases_count': len(results),
        'aggregate': {
            'quality_score': round(avg_quality, 3),
            'knowledge_coverage': round(avg_knowledge, 3),
            'file_coverage': round(avg_file, 3),
            'token_efficiency': round(avg_efficiency, 3),
            'average_tokens_used': int(avg_tokens),
            'grade': _grade(avg_quality),
        },
        'cases': results,
    }


def _grade(score: float) -> str:
    if score >= 0.9:
        return 'A+'
    elif score >= 0.8:
        return 'A'
    elif score >= 0.7:
        return 'B'
    elif score >= 0.6:
        return 'C'
    elif score >= 0.5:
        return 'D'
    return 'F'


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='ARGON End-to-End Benchmark')
    parser.add_argument('--output', help='Output file for results (JSON)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    print("[*] Running ARGON End-to-End Benchmark...")
    report = run_e2e_benchmark()

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[+] Results saved to {args.output}")

    agg = report['aggregate']
    print(f"\n{'='*60}")
    print("ARGON End-to-End Benchmark Results")
    print(f"{'='*60}")
    print(f"Cases: {report['cases_count']}")
    print(f"Quality Score: {agg['quality_score']:.3f} ({agg['grade']})")
    print(f"Knowledge Coverage: {agg['knowledge_coverage']:.3f}")
    print(f"File Coverage: {agg['file_coverage']:.3f}")
    print(f"Token Efficiency: {agg['token_efficiency']:.3f}")
    print(f"Average Tokens Used: {agg['average_tokens_used']}")
    print("\nPer-Case Results:")
    print(f"{'-'*60}")
    for case in report['cases']:
        print(f"  {case['case_id']}: Q={case['quality_score']:.3f} "
              f"K={case['knowledge_coverage']:.3f} "
              f"F={case['file_coverage']:.3f} "
              f"symbols={case['symbols_count']} "
              f"critical={case['critical_symbols']} "
              f"tokens={case['tokens_used']}")

    return 0 if agg['quality_score'] >= 0.5 else 1


if __name__ == '__main__':
    sys.exit(main())
