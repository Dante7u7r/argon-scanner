"""Project domain detection based on symbol names, imports, and summaries."""

from typing import Any, Dict, List, Optional, Tuple

from argon.models import ProjectNode

DOMAIN_KEYWORDS: Dict[str, set] = {
    'calculator': {'solve', 'calculate', 'compute', 'eval', 'expression', 'parser', 'ast', 'tokenize', 'matrix', 'equation', 'math', 'numeric', 'complex', 'vector'},
    'web_app': {'route', 'controller', 'middleware', 'handler', 'endpoint', 'api', 'request', 'response', 'server', 'http', 'router'},
    'e_commerce': {'order', 'payment', 'cart', 'checkout', 'product', 'inventory', 'shipping', 'refund', 'invoice'},
    'auth_system': {'login', 'authenticate', 'authorization', 'session', 'token', 'jwt', 'oauth', 'credential', 'password', 'user'},
    'data_pipeline': {'pipeline', 'etl', 'transform', 'ingest', 'stream', 'batch', 'queue', 'worker', 'job'},
    'game': {'entity', 'sprite', 'render', 'physics', 'collision', 'game', 'player', 'score', 'level', 'animation', 'canvas'},
    'desktop_app': {'window', 'dialog', 'menu', 'toolbar', 'statusbar', 'widget', 'gui', 'app', 'tauri', 'electron'},
    'library': {'export', 'module', 'package', 'publish', 'docs', 'example', 'api'},
    'cms': {'page', 'post', 'content', 'editor', 'template', 'theme', 'admin', 'blog'},
    'monitoring': {'telemetry', 'metrics', 'log', 'trace', 'monitor', 'alert', 'dashboard', 'health'},
}


def detect_project_domain(nodes: List[ProjectNode]) -> str:
    all_names = []
    all_imports = []
    all_summaries = []
    for n in nodes:
        all_names.extend(s.name.lower() for s in n.symbols)
        all_imports.extend(i.lower() for i in n.imports)
        if n.summary:
            all_summaries.append(n.summary.lower())
    combined = ' '.join(all_names + all_imports + all_summaries)
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[domain] = score
    if scores:
        return max(scores, key=scores.get)
    return 'general'


def detect_project_domain_ml(nodes: List[ProjectNode]) -> Tuple[str, Dict[str, float]]:
    try:
        from argon.engine.domain_ml import DomainDetector
        detector = DomainDetector()
        symbols = []
        imports = []
        summaries = []
        for n in nodes:
            for s in n.symbols:
                symbols.append({
                    'name': s.name,
                    'file': n.id,
                    'signature': s.signature,
                })
            imports.extend(n.imports)
            if n.summary:
                summaries.append(n.summary)
        domain, scores = detector.detect(symbols, imports, summaries)
        return domain, scores
    except Exception:
        return 'general', {}
