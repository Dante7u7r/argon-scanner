"""ML-based domain detection using embeddings or TF-IDF."""

import json
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

DOMAIN_PROTOTYPES = {
    'calculator': [
        'calculator math expression parser evaluate sum subtract multiply divide',
        'equation solver numerical computation formula evaluation solve compute',
        'arithmetic operations mathematical functions calculate result numeric matrix vector',
        'circuit solver spice netlist component resistor capacitor inductor diode',
        'node voltage current analysis frequency response impedance phase',
        'solver engine linear algebra matrix equation electron circuit',
        'expression tokenizer lexer parse ast abstract syntax tree precedence',
    ],
    'neural_simulation': [
        'neural network neuron synapse plasticity brain simulation',
        'biological cell membrane potential spike action potential',
        'cortical brain cortex neural dynamics simulation',
    ],
    'web_app': [
        'web application http server route handler endpoint api',
        'frontend backend database user authentication login',
        'react vue angular component page layout form submit',
    ],
    'e_commerce': [
        'product catalog shopping cart checkout payment order',
        'inventory stock price discount coupon shipping delivery',
        'customer account purchase transaction invoice receipt',
    ],
    'auth_system': [
        'authentication login password token session jwt oauth',
        'authorization permission role access control user identity',
        'credential security encrypt decrypt hash salt bcrypt',
    ],
    'data_pipeline': [
        'etl pipeline data transform extract load warehouse',
        'streaming batch processing queue worker job scheduler',
        'dataflow kafka rabbitmq airflow dag pipeline',
    ],
    'game': [
        'game engine entity component system sprite animation',
        'physics collision detection rendering shader opengl vulkan',
        'player input movement score level world scene',
    ],
    'library': [
        'library package module api public interface export',
        'utility function helper tool common shared reusable',
        'documentation readme examples usage installation',
    ],
    'cms': [
        'content management system page template theme layout',
        'article post blog comment category tag media',
        'admin dashboard editor richtext wysiswyg upload',
    ],
    'monitoring': [
        'monitoring alerting metric dashboard log trace',
        'prometheus grafana datadog newrelic monitoring',
        'health check uptime latency performance benchmark',
    ],
    'compiler': [
        'compiler lexer parser ast syntax token grammar',
        'interpreter bytecode vm virtual machine code generation',
        'type checker semantic analysis optimization pass',
    ],
    'database': [
        'database sql query table schema migration index',
        'orm model relationship foreign key join transaction',
        'connection pool repository pattern data access',
    ],
    'api': [
        'rest api endpoint route handler http request response',
        'graphql schema resolver mutation query subscription',
        'swagger openapi documentation api specification',
    ],
    'mobile': [
        'mobile app ios android flutter react native',
        'screen navigation gesture touch swipe scroll',
        'camera gps location notification push deep link',
    ],
    'ml_pipeline': [
        'machine learning model training inference prediction',
        'tensorflow pytorch sklearn dataset feature engineering',
        'neural network deep learning classification regression',
    ],
    'blockchain': [
        'blockchain cryptocurrency wallet transaction smart contract',
        'ethereum solidity mining proof stake consensus',
        'decentralized dapp token nft defi protocol',
    ],
    'iot': [
        'internet of things iot sensor device mqtt protocol',
        'embedded firmware microcontroller raspberry pi arduino',
        'telemetry data collection edge computing gateway',
    ],
    'financial': [
        'financial trading stock market portfolio investment',
        'banking payment transfer ledger accounting balance',
        'risk management compliance regulation audit report',
    ],
    'bioinformatics': [
        'bioinformatics genomics sequence alignment protein structure',
        'dna rna gene expression phylogenetic analysis',
        'biological pathway drug discovery molecular modeling',
    ],
    'devops': [
        'devops ci cd pipeline deployment docker kubernetes',
        'infrastructure terraform ansible chef puppet',
        'monitoring logging alerting incident response',
    ],
    'security': [
        'security vulnerability scanning penetration testing',
        'firewall intrusion detection encryption authentication',
        'compliance audit risk assessment security policy',
    ],
    'desktop_app': [
        'desktop application gui window dialog menu toolbar',
        'electron tauri qt wxwidgets native cross platform',
        'file system registry print clipboard drag drop',
        'webview frontend backend commands invoke ipc message',
        'canvas orchestrator oscilloscope render paint draw component',
    ],
    'scientific_computing': [
        'scientific computing numerical analysis simulation',
        'matrix vector linear algebra differential equation',
        'monte carlo optimization curve fitting interpolation',
    ],
    'media': [
        'media video audio image processing editing',
        'streaming playback recording codec format convert',
        'gallery album playlist timeline social feed',
    ],
}


def _tokenize(text: str) -> List[str]:
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[_\-./:\\@]+', ' ', text)
    tokens = re.findall(r'[a-zA-Z0-9]+', text.lower())
    return [t for t in tokens if len(t) > 1]


def _compute_tfidf(texts: List[str]) -> Tuple[Dict[str, float], List[Dict[str, float]]]:
    doc_tokens = [_tokenize(t) for t in texts]
    n = len(doc_tokens)
    df: Counter = Counter()
    for tokens in doc_tokens:
        for t in set(tokens):
            df[t] += 1
    idf = {t: math.log((n + 1) / (count + 1)) + 1 for t, count in df.items()}
    vectors = []
    for tokens in doc_tokens:
        tf = Counter(tokens)
        total = len(tokens) or 1
        vec = {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}
        vectors.append(vec)
    return idf, vectors


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    dot = sum(a[k] * b[k] for k in a if k in b)
    if dot == 0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class DomainDetector:
    def __init__(self):
        self._prototype_idf = None
        self._prototype_vectors = None
        self._domain_names = list(DOMAIN_PROTOTYPES.keys())
        self._build_prototypes()

    def _build_prototypes(self) -> None:
        all_texts = []
        for domain, examples in DOMAIN_PROTOTYPES.items():
            all_texts.extend(examples)
        self._prototype_idf, all_vectors = _compute_tfidf(all_texts)
        self._prototype_vectors = []
        idx = 0
        for domain, examples in DOMAIN_PROTOTYPES.items():
            domain_vectors = all_vectors[idx:idx + len(examples)]
            if domain_vectors:
                combined: Dict[str, float] = {}
                for vec in domain_vectors:
                    for k, v in vec.items():
                        combined[k] = combined.get(k, 0) + v / len(domain_vectors)
                self._prototype_vectors.append(combined)
            else:
                self._prototype_vectors.append({})
            idx += len(examples)

    def detect(self, symbols: List[Dict[str, Any]], imports: List[str] = None, summaries: List[str] = None) -> Tuple[str, Dict[str, float]]:
        parts = []
        for sym in symbols[:50]:
            parts.append(sym.get('name', ''))
            parts.append(sym.get('file', ''))
            parts.append(sym.get('signature', ''))
        if imports:
            parts.extend(imports[:30])
        if summaries:
            parts.extend(summaries[:10])
        text = ' '.join(parts)
        project_tokens = _tokenize(text)
        project_tf = Counter(project_tokens)
        total = len(project_tokens) or 1
        project_vec = {t: (c / total) * self._prototype_idf.get(t, 1.0) for t, c in project_tf.items()}
        scores = {}
        for i, domain in enumerate(self._domain_names):
            if i < len(self._prototype_vectors):
                scores[domain] = _cosine(project_vec, self._prototype_vectors[i])
            else:
                scores[domain] = 0.0
        best_domain = max(scores, key=scores.get) if scores else 'unknown'
        return best_domain, scores


def detect_project_domain(symbols: List[Dict[str, Any]], imports: List[str] = None, summaries: List[str] = None) -> str:
    detector = DomainDetector()
    domain, _ = detector.detect(symbols, imports, summaries)
    return domain
