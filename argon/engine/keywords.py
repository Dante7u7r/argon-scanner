"""Keyword extraction, stop words, and synonym expansion for task matching."""

import re
from collections import defaultdict
from typing import Dict, List

STOP_WORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'and', 'or', 'not', 'this', 'that', 'it', 'i', 'we', 'you', 'need', 'want', 'make', 'add',
    'when', 'while', 'during', 'after', 'before',
    'fix', 'update', 'change', 'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en', 'con',
    'por', 'para', 'que', 'como', 'es', 'son', 'hay', 'quiero', 'necesito', 'hacer', 'crear',
    'modificar', 'arreglar',
})

_FULL_EXPAND_GROUPS = {
    'auth', 'login', 'token', 'payment', 'billing', 'cache', 'order',
    'cancel', 'rate', 'pagination', 'validation', 'middleware', 'error',
    'config', 'async', 'email', 'notification', 'search', 'permission',
    'webhook', 'test', 'security', 'neural', 'simulation', 'biology',
    'math', 'physics', 'deploy', 'monitoring', 'serialization',
    'performance', 'error_handling', 'refactor', 'dependency',
    'stream', 'upload',
    'total', 'placement',
}

SYNONYM_GROUPS = {
    'auth': {
        'auth', 'authenticate', 'authentication', 'authenticated', 'authorise',
        'authorize', 'authorization', 'login', 'logins', 'logged', 'logs', 'signin', 'session',
        'token', 'jwt', 'oauth', 'credential', 'credentials', 'passport',
    },
    'login': {'login', 'logins', 'logged', 'logs', 'signin', 'signout', 'logout', 'auth', 'authenticate', 'authentication'},
    'token': {'token', 'jwt', 'access', 'refresh', 'bearer', 'auth', 'authentication'},
    'user': {'user', 'users', 'email', 'account', 'profile', 'member', 'membership'},
    'payment': {
        'payment', 'pay', 'paid', 'transaction', 'transactions', 'refund', 'refunded',
        'checkout', 'invoice', 'billing', 'charge', 'charges', 'receipt',
    },
    'billing': {'billing', 'bill', 'invoice', 'invoicing', 'receipt', 'charge', 'charges', 'purchase', 'purchasing', 'subscription', 'subscribe', 'subscriber', 'payer', 'payee', 'statement'},
    'cache': {'cache', 'cached', 'caching', 'invalidation', 'invalidate', 'invalidated'},
    'order': {'order', 'orders', 'checkout', 'cart', 'cartitem', 'purchase', 'fulfillment'},
    'placement': {'placement', 'place', 'placing', 'submit'},
    'cancel': {'cancel', 'cancellation', 'cancelled', 'canceled'},
    'total': {'total', 'sum', 'price', 'amount', 'calculate', 'calculation'},
    'rate': {'rate', 'limiting', 'limit', 'throttle', 'throttling', 'cooldown', 'ratelimit'},
    'endpoint': {'endpoint', 'route', 'routes', 'router', 'api', 'handler', 'handlers'},
    'pagination': {'pagination', 'paginate', 'page', 'offset', 'cursor', 'scroll'},
    'validation': {'validation', 'validate', 'validator', 'schema', 'pydantic', 'joi', 'sanitize'},
    'migration': {'migration', 'migrate', 'schema', 'database', 'db', 'alembic'},
    'middleware': {'middleware', 'interceptor', 'guard', 'hook', 'plugin'},
    'error': {'error', 'exception', 'exceptions', 'raise', 'throw', 'catch', 'handle', 'handling'},
    'config': {'config', 'configuration', 'settings', 'env', 'environment', 'secrets', 'options'},
    'logging': {'logging', 'log', 'logger', 'debug', 'info', 'warn', 'trace'},
    'async': {'async', 'await', 'concurrent', 'parallel', 'thread', 'worker', 'sync', 'ensure_sync', 'coroutine', 'event_loop', 'background', 'background_task', 'task', 'tasks', 'scheduler'},
    'email': {'email', 'mail', 'smtp', 'send', 'sendgrid', 'notification', 'notify', 'mailer', 'mailgun'},
    'notification': {'notification', 'notify', 'notifications', 'alert', 'alerts', 'push', 'inbox'},
    'stream': {'stream', 'streaming', 'chunk', 'chunks', 'chunked', 'download', 'upload', 'iter_content', 'read_bytes', 'read', 'raw'},
    'upload': {'upload', 'uploaded', 'file', 'files', 'attachment', 'multipart', 'formdata', 'download', 'stream', 'streaming'},
    'permission': {'permission', 'permissions', 'role', 'roles', 'access', 'acl', 'rbac', 'policy'},
    'webhook': {'webhook', 'webhooks', 'callback', 'callbacks', 'event', 'events'},
    'test': {'test', 'tests', 'testing', 'spec', 'specs', 'unittest', 'integration'},
    'security': {'security', 'secure', 'encrypt', 'decrypt', 'hash', 'sanitize', 'xss', 'csrf', 'attack'},
    'neural': {'neural', 'neuron', 'neurons', 'synapse', 'synapses', 'plasticity', 'spike', 'spikes', 'axon', 'dendrite', 'dendrites', 'brain', 'cortex', 'cortical', 'excitatory', 'inhibitory', 'lfp', 'oscillation'},
    'simulation': {'simulate', 'simulation', 'simulated', 'model', 'modeling', 'parameter', 'parameters', 'iteration', 'iterations', 'convergence', 'step', 'timestep', 'integration'},
    'biology': {'cell', 'cells', 'gene', 'genes', 'protein', 'proteins', 'evolution', 'evolutionary', 'mutation', 'mutations', 'fitness', 'organism', 'organisms', 'tissue', 'membrane'},
    'math': {'matrix', 'matrices', 'vector', 'vectors', 'eigenvalue', 'derivative', 'derivatives', 'integral', 'integrals', 'gradient', 'optimization', 'optimization', 'convergence', 'linear', 'algebra'},
    'physics': {'force', 'velocity', 'acceleration', 'mass', 'energy', 'momentum', 'collision', 'friction', 'gravity', 'electromagnetic', 'quantum', 'thermodynamic'},
    'database': {'query', 'queries', 'table', 'tables', 'schema', 'schemas', 'index', 'indexes', 'transaction', 'transactions', 'cursor', 'join', 'joins', 'sql', 'orm'},
    'api': {'endpoint', 'endpoints', 'route', 'routes', 'handler', 'handlers', 'request', 'requests', 'response', 'responses', 'status', 'header', 'headers', 'rest', 'graphql', 'payload', 'body', 'param', 'params'},
    'deploy': {'deploy', 'deployment', 'container', 'containers', 'docker', 'kubernetes', 'k8s', 'pipeline', 'pipelines', 'ci', 'cd', 'provisioning'},
    'monitoring': {'metric', 'metrics', 'alert', 'alerts', 'dashboard', 'dashboards', 'log', 'logs', 'logging', 'logger', 'trace', 'traces', 'health', 'uptime', 'latency'},
    'ui': {'component', 'components', 'render', 'rendering', 'layout', 'layouts', 'button', 'buttons', 'modal', 'modals', 'form', 'forms', 'input', 'inputs', 'dropdown', 'navigation'},
    'data': {'data', 'dataset', 'datasets', 'pipeline', 'etl', 'transform', 'transform', 'ingest', 'stream', 'batch', 'queue', 'worker', 'workers', 'job', 'jobs'},
    'import': {'import', 'imports', 'require', 'export', 'exports', 'dependency', 'dependencies', 'module', 'modules'},
    'serialization': {'serialize', 'deserialize', 'serializer', 'json', 'marshalling', 'marshal', 'unmarshal', 'codec', 'encode', 'decode'},
    'performance': {'performance', 'perf', 'optimize', 'optimization', 'slow', 'fast', 'latency', 'throughput', 'speed', 'efficient', 'efficiency', 'bottleneck', 'profile', 'profiling'},
    'error_handling': {'error_handling', 'error', 'errors', 'exception', 'exceptions', 'crash', 'crashes', 'resilience', 'retry', 'fallback', 'graceful', 'degradation', 'recovery'},
    'refactor': {'refactor', 'refactoring', 'restructure', 'reorganize', 'cleanup', 'simplify', 'extract', 'decouple', 'decoupling', 'modularize'},
    'dependency': {'dependency', 'dependencies', 'deps', 'upgrade', 'update', 'bump', 'version', 'versions', 'compatibility', 'breaking'},
}


def extract_task_keywords(task: str, identifier_tokens_fn=None) -> List[str]:
    from argon.engine.scorer import identifier_tokens as _default_id_tokens
    if identifier_tokens_fn is None:
        identifier_tokens_fn = _default_id_tokens

    words: List[str] = []
    for raw in re.findall(r'[\w@./-]+', task):
        words.extend(identifier_tokens_fn(raw))
    keywords = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
    return _expand_keywords(keywords)


def _expand_keywords(keywords: List[str]) -> List[str]:
    reverse_synonyms: Dict[str, List[str]] = defaultdict(list)
    for canonical, aliases in SYNONYM_GROUPS.items():
        for alias in aliases:
            if canonical not in reverse_synonyms[alias]:
                reverse_synonyms[alias].append(canonical)

    expanded: List[str] = []
    for word in keywords:
        expanded.append(word)
        for canonical in reverse_synonyms.get(word, []):
            expanded.append(canonical)
            if canonical in _FULL_EXPAND_GROUPS:
                expanded.extend(sorted(SYNONYM_GROUPS.get(canonical, [])))
    return list(dict.fromkeys(expanded))
