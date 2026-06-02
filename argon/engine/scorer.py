"""Symbol scoring, tokenization, IDF computation, and noise filtering."""

import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from argon.utils.noise import SYMBOL_NOISE


def identifier_tokens(text: str) -> List[str]:
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[@./_\-]+', ' ', text)
    return [p.lower() for p in re.findall(r'[A-Za-z0-9]+', text)]


def symbol_tokens(sym: Dict[str, Any]) -> Set[str]:
    chunks = [
        sym.get('id', ''),
        sym.get('name', ''),
        sym.get('file', ''),
        sym.get('kind', ''),
        sym.get('signature', ''),
    ]
    out: List[str] = []
    for chunk in chunks:
        out.extend(identifier_tokens(str(chunk)))
    return set(out)


def symbol_match_profile(sym: Dict[str, Any], keywords: List[str]) -> Dict[str, Set[str]]:
    task_tokens = set(keywords)
    return {
        'name': task_tokens & set(identifier_tokens(sym.get('name', ''))),
        'file': task_tokens & set(identifier_tokens(sym.get('file', ''))),
        'signature': task_tokens & set(identifier_tokens(sym.get('signature', ''))),
        'all': task_tokens & symbol_tokens(sym),
    }


def is_noise_symbol_for_task(sym: Dict[str, Any]) -> bool:
    name = str(sym.get('name', ''))
    signature = str(sym.get('signature', '')).strip()
    if name in SYMBOL_NOISE:
        return True
    if signature.startswith(('raise ', 'throw new ')) and name.endswith('Error'):
        return True
    declaration_prefixes = (
        'def ', 'async def ', 'class ', 'export ', 'function ', 'async function ',
        'const ', 'let ', 'var ', 'interface ', 'type ', 'enum ',
        'public ', 'private ', 'protected ', 'static ', 'final ', 'void ',
        'boolean ', 'string ', 'int ', 'long ', 'double ', 'float ', 'decimal ',
        'namespace ', 'using ',
    )
    if (
        str(sym.get('kind', '')).lower() == 'func'
        and signature
        and not signature.startswith(declaration_prefixes)
        and (
            int(sym.get('start_line') or 0) == int(sym.get('end_line') or 0)
            or signature.endswith(')')
            or ('{' not in signature and '=>' not in signature and not signature.endswith(':'))
        )
        and not sym.get('exported')
    ):
        return True
    return False


def symbol_token_cost(sym: Dict[str, Any], token_counter, include_code: bool = True, read_snippet_fn=None) -> int:
    snippet = ""
    if include_code and read_snippet_fn:
        snippet = read_snippet_fn(sym)
    preview = {
        'id': sym.get('id', ''),
        'file': sym.get('file', ''),
        'kind': sym.get('kind', ''),
        'signature': sym.get('signature', ''),
        'reasons': sym.get('selection_reasons', []),
        'code': snippet,
    }
    return max(1, token_counter.count(json.dumps(preview, ensure_ascii=False)))


def task_focus_tokens(keywords: List[str]) -> Set[str]:
    entity_tokens = {
        'item', 'items', 'model', 'models',
        'data', 'support', 'bug', 'wrong', 'empty', 'strategy',
    }
    return {kw for kw in keywords if kw not in entity_tokens}


def task_intents(task: str) -> Set[str]:
    words: Set[str] = set()
    for raw in re.findall(r'[\w@./-]+', task.lower()):
        for tok in identifier_tokens(raw):
            if len(tok) > 2:
                words.add(tok)
    intents: Set[str] = set()
    if words & {'bug', 'fix', 'fail', 'failure', 'error', 'regression', 'broken', 'crash', 'incorrect', 'exception', 'bugfix', 'fallo', 'arreglar'}:
        intents.add('bugfix')
    if words & {'test', 'tests', 'spec', 'coverage', 'unittest', 'prueba', 'pruebas'}:
        intents.add('tests')
    if words & {'type', 'types', 'interface', 'schema', 'typing', 'tipo', 'tipos'}:
        intents.add('types')
    return intents


def is_generic_type_symbol(sym: Dict[str, Any]) -> bool:
    kind = str(sym.get('kind', '')).lower()
    if kind not in {'symbol', 'interface', 'type', 'enum', 'struct'}:
        return False
    return (
        int(sym.get('named_imports') or 0) >= 25 and
        int(sym.get('inbound_calls') or 0) == 0
    )


def is_weak_file_only_match(sym: Dict[str, Any], keywords: List[str]) -> bool:
    profile = symbol_match_profile(sym, keywords)
    if profile['name'] or profile['signature']:
        return False
    if not profile['file']:
        return False
    return True


def is_unrequested_test_symbol(sym: Dict[str, Any], intents: Set[str]) -> bool:
    if 'tests' in intents:
        return False
    file_path = str(sym.get('file', '')).lower().replace('\\', '/')
    return '/test' in f'/{file_path}' or file_path.endswith('_test.py') or file_path.endswith('.test.ts')


def is_isolated_focus_match(sym: Dict[str, Any], keywords: List[str]) -> bool:
    profile = symbol_match_profile(sym, keywords)
    focus = task_focus_tokens(keywords)
    if not (focus & (profile['name'] | profile['signature'])):
        return False
    structural_signal = (
        int(sym.get('inbound_calls') or 0)
        + int(sym.get('outbound_calls') or 0)
        + int(sym.get('named_imports') or 0)
        + int(sym.get('resolved_imports') or 0)
    )
    if structural_signal > 0:
        return False
    file_path = str(sym.get('file', '')).lower().replace('\\', '/')
    distractor_segments = {'noise', 'noisy', 'mock', 'mocks', 'sample', 'samples', 'fixture', 'fixtures'}
    return any(f'/{segment}/' in f'/{file_path}' for segment in distractor_segments)


_score_cache: Dict[Tuple[str, ...], Tuple[float, int]] = {}


def clear_score_cache() -> None:
    _score_cache.clear()


def score_symbol_for_task(sym: Dict[str, Any], keywords: List[str], idf: Optional[Dict[str, float]] = None, false_positive_blacklist: Optional[set] = None, semantic_index=None, task_text: str = "") -> Tuple[float, int]:
    if not keywords:
        return 0.0, 0
    key = (sym.get('id', ''),) + tuple(sorted(keywords))
    cached = _score_cache.get(key)
    if cached is not None:
        return cached
    profile = symbol_match_profile(sym, keywords)
    overlap = profile['all']
    score = 0.0
    name_weight = 5.0
    file_weight = 1.6
    sig_weight = 1.5
    overlap_weight = 0.6
    if idf:
        for kw in profile['name']:
            name_weight += idf.get(kw, 1.0) * 0.5
        for kw in profile['file']:
            file_weight += idf.get(kw, 1.0) * 0.3
    score += len(profile['name']) * name_weight
    score += len(profile['file']) * file_weight
    score += len(profile['signature']) * sig_weight
    score += max(0, len(overlap) - len(profile['name'])) * overlap_weight
    focus = task_focus_tokens(keywords)
    if (
        focus & profile['file']
        and str(sym.get('kind', '')).lower() == 'func'
        and sym.get('exported')
        and 'test' not in str(sym.get('file', '')).lower()
        and 'spec' not in str(sym.get('file', '')).lower()
    ):
        score += 1.2

    lower_name = sym.get('name', '').lower()
    lower_file = sym.get('file', '').lower()
    name_tokens = set(identifier_tokens(sym.get('name', '')))
    for kw in keywords:
        kw_idf = idf.get(kw, 1.0) if idf else 1.0
        kw_ic = (kw_idf - 1.0) * 0.8 if idf else 0.0
        if false_positive_blacklist:
            is_fp = any((kw, tok) in false_positive_blacklist for tok in name_tokens)
            if is_fp:
                continue
        if kw in lower_name:
            if kw in name_tokens:
                score += 1.5 * kw_idf * (1.0 + kw_ic)
            elif any(t.startswith(kw) and len(t) > len(kw) for t in name_tokens):
                score += 0.8 * kw_idf * (1.0 + kw_ic * 0.5)
            else:
                score += 0.2 * kw_idf
        if kw in lower_file:
            score += 0.45 * kw_idf * (1.0 + kw_ic * 0.3)
        for token in name_tokens:
            if len(token) > 4 and len(kw) > 3 and kw == token:
                score += 0.5 * kw_idf
                break

    if semantic_index and task_text:
        sem_results = semantic_index.query(task_text, top_k=1)
        if sem_results:
            sem_score, sem_sym = sem_results[0]
            if sem_sym.get('id') == sym.get('id'):
                score = 0.7 * score + 0.3 * (sem_score * 10)

    result = (score, len(overlap))
    _score_cache[key] = result
    return result


def compute_idf(symbols: List[Dict[str, Any]]) -> Dict[str, float]:
    doc_count = len(symbols)
    if doc_count == 0:
        return {}
    token_doc_freq: Dict[str, int] = defaultdict(int)
    for sym in symbols:
        tokens = symbol_tokens(sym)
        seen = set()
        for token in tokens:
            if token not in seen:
                token_doc_freq[token] += 1
                seen.add(token)
    return {token: math.log((doc_count + 1) / (freq + 1)) + 1 for token, freq in token_doc_freq.items()}
