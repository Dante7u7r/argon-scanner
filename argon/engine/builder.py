import concurrent.futures
import datetime
import json
import os
import re
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from argon.models import ProjectNode, Symbol
from argon.parser import UniversalParser
from argon.parser.regex import _infer_symbol_end_line
from argon.resolvers.ignore import IgnoreMatcher
from argon.resolvers.imports import ImportResolver, _is_probable_external_import
from argon.utils.noise import STDLIB_NOISE
from argon.utils.tokens import TokenCounter
from argon.engine.roles import classify_file_roles, role_score_boost
from argon.engine.communities import detect_communities
from argon.engine.test_gaps import detect_testing_gaps
from argon.engine.debt import scan_file_for_debt, scan_project_for_debt


def _pagerank(node_ids: List[str], edges: List[Dict[str, str]], iterations: int = 40, damping: float = 0.85, convergence_threshold: float = 1e-6) -> Dict[str, float]:
    if not node_ids:
        return {}
    ids = list(dict.fromkeys(node_ids))
    n = len(ids)
    if n == 0:
        return {}
    incoming: Dict[str, List[str]] = {i: [] for i in ids}
    outgoing_count: Dict[str, int] = {i: 0 for i in ids}
    valid = set(ids)
    for edge in edges:
        src, dst = edge.get('source'), edge.get('target')
        if src in valid and dst in valid and src != dst:
            incoming[dst].append(src)
            outgoing_count[src] += 1
            
    sinks = [i for i in ids if outgoing_count[i] == 0]
    inv_outgoing = {i: 1.0 / outgoing_count[i] for i in ids if outgoing_count[i] > 0}
    rank = {i: 1.0 / n for i in ids}
    
    d_div_n = (1.0 - damping) / n
    damping_div_n = damping / n
    
    for _ in range(iterations):
        sink = sum(rank[i] for i in sinks)
        const_term = d_div_n + damping_div_n * sink
        new_rank = {}
        delta = 0.0
        for i in ids:
            value = const_term + damping * sum(rank[src] * inv_outgoing[src] for src in incoming[i])
            new_rank[i] = value
            delta += abs(value - rank[i])
        rank = new_rank
        if delta < convergence_threshold:
            break
    max_rank = max(rank.values()) or 1
    return {k: v / max_rank for k, v in rank.items()}


class BuilderMixin:
    def __init__(self, root_dir: str, precision: bool = False, model: str = "gpt-4.1",
                 output_dir: str = "", has_tree_sitter: Optional[bool] = None,
                 has_tiktoken: Optional[bool] = None,
                 has_pathspec: Optional[bool] = None, ts_pack=None, tiktoken_mod=None,
                 pathspec_mod=None, semantic_index=None):
        if has_tree_sitter is None:
            try:
                import tree_sitter_language_pack as tsp
                ts_pack = tsp
                has_tree_sitter = True
            except ImportError:
                has_tree_sitter = False
        if has_pathspec is None:
            try:
                import pathspec as ps
                has_pathspec = True
                if pathspec_mod is None:
                    pathspec_mod = ps
            except ImportError:
                has_pathspec = False
        self.root = os.path.abspath(root_dir)
        self.output_dir = os.path.abspath(output_dir) if output_dir else ''
        self.precision = precision
        self.model = model
        self.token_counter = TokenCounter(model=model, strict=precision, has_tiktoken=has_tiktoken, tiktoken_mod=tiktoken_mod)
        self.ignore_matcher = IgnoreMatcher(self.root, has_pathspec=has_pathspec, pathspec_mod=pathspec_mod) if precision else None
        self.extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.sql', '.c', '.cpp', '.h', '.hpp',
            '.java', '.go', '.rs', '.php', '.rb', '.cs', '.sh', '.bat', '.ps1',
            '.swift', '.kt', '.scala', '.ex', '.exs', '.lua', '.r', '.jl',
        }
        if not precision:
            self.extensions.update({'.md', '.json', '.yaml', '.yml', '.toml', '.ini', '.xml', '.html', '.css'})
        self.skip_dirs = {
            '__pycache__', '.git', 'node_modules', 'venv', '.venv',
            'dist', 'build', '.next', 'target', '.cache', 'coverage',
            '.pytest_cache', '.argon_cache', '.agents', 'vendor', 'bin', 'obj', '.idea', '.vs',
        }
        self.skip_files = {
            'argon_graph.json', 'ARGON.md', 'argon_view.html', '.argon_cache.json',
            'argon.py', 'argon_mcp.py', 'argon_view.py', 'argon_watch.py',
            'argon_template.html',
        }
        self.false_positive_blacklist = {
            ('payment', 'timeout'), ('payment', 'settimeout'), ('email', 'mailinglist'),
            ('auth', 'checkbox'), ('auth', 'pathname'), ('cache', 'workspace'),
            ('search', 'research'), ('test', 'testing_framework'), ('order', 'border'),
        }
        self.parser = UniversalParser(
            self.root,
            has_tree_sitter=has_tree_sitter,
            has_process=hasattr(ts_pack, 'process') if ts_pack else False,
            ts_pack=ts_pack,
        )
        self.semantic_index = semantic_index

    def _should_skip(self, path: str, is_dir: bool) -> bool:
        name = os.path.basename(path)
        if self.ignore_matcher and self.ignore_matcher.match(path, is_dir):
            return True
        if is_dir:
            return name in self.skip_dirs or name.startswith('.') and name not in ('.cursor', '.github')
        try:
            sz = os.path.getsize(path)
        except OSError:
            return True
        return (
            name in self.skip_files or
            name.startswith('ARGON_PRECISION.') or
            os.path.splitext(name)[1].lower() not in self.extensions or
            sz > 2_000_000
        )

    def _cache_path(self) -> str:
        base = self.output_dir if self.output_dir else self.root
        return os.path.join(base, '.argon_cache.json')

    def _load_parse_cache(self) -> Dict[str, Any]:
        try:
            with open(self._cache_path(), 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('files', {}) if data.get('version') == 1 else {}
        except Exception:
            return {}

    def _save_parse_cache(self, cache: Dict[str, Any]) -> None:
        try:
            with open(self._cache_path(), 'w', encoding='utf-8') as f:
                json.dump({'version': 1, 'files': cache}, f, ensure_ascii=False)
        except Exception:
            return

    def _node_from_cache(self, data: Dict[str, Any]) -> ProjectNode:
        node = ProjectNode(
            id=data['id'],
            type=data.get('type', ''),
            lines=data.get('lines', 0),
            size_bytes=data.get('size_bytes', 0),
            imports=data.get('imports', []),
            import_records=data.get('import_records', []),
            exports=data.get('exports', []),
            unresolved_imports=data.get('unresolved_imports', []),
            resolved_imports=data.get('resolved_imports', {}),
            summary=data.get('summary', ''),
            importance=data.get('importance', 0.0),
            pagerank=data.get('pagerank', 0.0),
        )
        node.symbols = [Symbol(**sym) for sym in data.get('symbols', [])]
        return node

    def _compute_importance(self, nodes: List[ProjectNode], edges: List[Dict]) -> None:
        ranks = _pagerank([n.id for n in nodes], edges) if self.precision else {}
        conn: Dict[str, int] = defaultdict(int)
        for e in edges:
            conn[e['source']] += 1
            conn[e['target']] += 1
        max_c = max(conn.values()) if conn else 1
        max_l = max((n.lines for n in nodes), default=1) or 1
        max_s = max((len(n.symbols) for n in nodes), default=1) or 1
        for n in nodes:
            c = conn.get(n.id, 0) / max_c
            l = n.lines / max_l
            s = len(n.symbols) / max_s
            n.pagerank = round(ranks.get(n.id, 0.0), 6)
            if self.precision:
                n.importance = round((n.pagerank * 0.7) + (c * 0.2) + (s * 0.1), 4)
            else:
                n.importance = round(c * 0.6 + l * 0.3 + s * 0.1, 4)

    def _detect_project_domain(self, nodes: List[ProjectNode]) -> str:
        try:
            from argon.engine.domain import detect_project_domain_ml as _detect_project_domain_ml_fn
            ml_domain, _ = _detect_project_domain_ml_fn(nodes)
            if ml_domain and ml_domain != 'general':
                return ml_domain
        except Exception:
            pass
        from argon.engine.domain import detect_project_domain as _detect_project_domain_fn
        return _detect_project_domain_fn(nodes)

    def _parse_one(self, fpath: str, rel: str, parse_cache: dict) -> Tuple[ProjectNode, str, os.stat_result, bool]:
        stat = os.stat(fpath)
        cached = parse_cache.get(rel)
        if cached and cached.get('mtime') == stat.st_mtime and cached.get('size') == stat.st_size:
            return self._node_from_cache(cached['node']), rel, stat, True
        return self.parser.parse(fpath), rel, stat, False

    def build_graph(self, workers: Optional[int] = None, changed_files: Optional[List[str]] = None) -> Dict[str, Any]:
        nodes: List[ProjectNode] = []
        print(f"[*] ARGON v9.0 — Escaneando: {self.root}")
        print(f"[*] Parser: {self.parser.mode.upper()}")
        parse_cache = self._load_parse_cache()
        next_cache: Dict[str, Any] = {}
        cache_hits = 0

        files: List[Tuple[str, str]] = []
        if changed_files is not None:
            changed_set = set(changed_files)
            for rel, entry in parse_cache.items():
                if rel in changed_set:
                    continue
                fpath = os.path.join(self.root, rel)
                try:
                    st = os.stat(fpath)
                except OSError:
                    continue
                if entry.get('mtime') == st.st_mtime and entry.get('size') == st.st_size:
                    node = self._node_from_cache(entry['node'])
                    nodes.append(node)
                    next_cache[rel] = entry
                    cache_hits += 1
                else:
                    changed_set.add(rel)

            for rel in changed_set:
                fpath = os.path.join(self.root, rel)
                if not os.path.exists(fpath):
                    continue
                if self._should_skip(fpath, False):
                    continue
                files.append((fpath, rel))
        else:
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [
                    d for d in dirnames
                    if not self._should_skip(os.path.join(dirpath, d), True)
                ]
                for f in filenames:
                    fpath = os.path.join(dirpath, f)
                    if self._should_skip(fpath, False):
                        continue
                    rel = os.path.relpath(fpath, self.root).replace('\\', '/')
                    files.append((fpath, rel))

        if workers is None:
            workers = min(8, (os.cpu_count() or 1) + 1)
        is_parallel = workers > 1 and self.parser.mode == 'regex'

        if not is_parallel:
            for fpath, rel in files:
                try:
                    node, rel2, stat, cache_hit = self._parse_one(fpath, rel, parse_cache)
                except OSError:
                    continue
                nodes.append(node)
                next_cache[rel] = {'mtime': stat.st_mtime, 'size': stat.st_size, 'node': node.to_dict()}
                if cache_hit:
                    cache_hits += 1
        else:
            lock = threading.Lock()
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {executor.submit(self._parse_one, fpath, rel, parse_cache): (fpath, rel) for fpath, rel in files}
                for future in concurrent.futures.as_completed(future_map):
                    fpath, rel = future_map[future]
                    try:
                        node, rel2, stat, cache_hit = future.result()
                    except OSError:
                        continue
                    with lock:
                        nodes.append(node)
                        next_cache[rel] = {'mtime': stat.st_mtime, 'size': stat.st_size, 'node': node.to_dict()}
                        if cache_hit:
                            cache_hits += 1

        edges = []
        seen_edges: Set[tuple] = set()

        if self.precision:
            resolver = ImportResolver(self.root, nodes)
            for n in nodes:
                records = n.import_records or [{'source': imp, 'line': 0, 'names': [], 'kind': 'import'} for imp in n.imports]
                for record in records:
                    imp = record.get('source', '')
                    target = resolver.resolve(n.id, imp)
                    if target:
                        n.resolved_imports[imp] = target
                        edge = (n.id, target)
                        if edge not in seen_edges:
                            edges.append({
                                'source': n.id,
                                'target': target,
                                'import': imp,
                                'line': record.get('line', 0),
                                'kind': record.get('kind', 'import'),
                                'names': record.get('names', []),
                                'specifiers': record.get('specifiers', []),
                            })
                            seen_edges.add(edge)
                    elif imp and not imp.startswith(('http://', 'https://')):
                        if _is_probable_external_import(imp):
                            continue
                        root = imp.split('/')[0].lstrip('@')
                        if root.lower() not in STDLIB_NOISE:
                            n.unresolved_imports.append(imp)
        else:
            node_ids = {n.id for n in nodes}
            path_index: Dict[str, Set[str]] = defaultdict(set)
            for nid in node_ids:
                base = nid.rsplit('.', 1)[0]
                path_index[base].add(nid)
                path_index[base.split('/')[-1]].add(nid)

            AMBIGUOUS_NAMES = {'utils', 'helpers', 'config', 'types', 'index', 'main', 'constants', 'common', 'models', 'views'}

            for n in nodes:
                n_dir = '/'.join(n.id.split('/')[:-1])
                for imp in n.imports:
                    clean = imp.replace('.', '/').strip('/')
                    imp_base = clean.split('/')[-1]
                    candidates = set()
                    if clean in path_index:
                        candidates |= path_index[clean]
                    if imp_base in path_index:
                        candidates |= path_index[imp_base]

                    scored = []
                    for tid in candidates:
                        if tid == n.id:
                            continue
                        tb = tid.rsplit('.', 1)[0]
                        if tb.endswith(clean) or tb == clean or clean == tb.split('/')[-1]:
                            td = '/'.join(tid.split('/')[:-1])
                            if td == n_dir:
                                scored.append((3, tid))
                            elif td.startswith(n_dir) or n_dir.startswith(td):
                                scored.append((2, tid))
                            else:
                                scored.append((1, tid))

                    if scored:
                        scored.sort(key=lambda x: x[0], reverse=True)
                        if len(scored) > 1 and imp_base in AMBIGUOUS_NAMES:
                            scored = scored[:1]
                        for _, tid in scored:
                            edge = (n.id, tid)
                            if edge not in seen_edges:
                                edges.append({'source': n.id, 'target': tid})
                                seen_edges.add(edge)

        self._compute_importance(nodes, edges)

        roles = classify_file_roles(nodes, edges)
        for node in nodes:
            node.role = roles.get(node.id, 'module')

        symbol_nodes = self._build_symbol_graph(nodes, edges) if self.precision else []
        symbol_edges = self._resolve_symbol_edges(nodes, edges)[0] if self.precision else []
        symbol_calls = [e for e in symbol_edges if e.get('kind') in ('calls-symbol', 'calls-symbol-local')]
        symbol_calls_imported = [e for e in symbol_edges if e.get('kind') == 'calls-symbol']
        symbol_calls_local = [e for e in symbol_edges if e.get('kind') == 'calls-symbol-local']

        project_domain = self._detect_project_domain(nodes)

        testing_gaps = detect_testing_gaps([n.id for n in nodes])
        debt_scan = scan_project_for_debt(self.root, [n.id for n in nodes])
        communities = detect_communities(
            [n.to_dict() for n in nodes],
            edges,
        )

        graph = {
            'root': os.path.basename(self.root),
            'nodes': [n.to_dict() for n in nodes],
            'edges': edges,
            'symbols': symbol_nodes,
            'symbol_edges': symbol_edges,
            'parser_mode': self.parser.mode,
            'precision': self.precision,
            'model': self.model,
            'project_domain': project_domain,
            'communities': communities,
            'testing_gaps': testing_gaps,
            'debt': {
                'total_markers': debt_scan['total_markers'],
                'by_severity': debt_scan['by_severity'],
                'by_tag': debt_scan['by_tag'],
                'files_with_markers': debt_scan['files_with_markers'],
            },
            'stats': {
                'total_files': len(nodes),
                'total_connections': len(edges),
                'total_symbols': sum(len(n.symbols) for n in nodes),
                'total_symbol_connections': len(symbol_edges),
                'total_symbol_calls': len(symbol_calls),
                'total_symbol_calls_imported': len(symbol_calls_imported),
                'total_symbol_calls_local': len(symbol_calls_local),
                'unresolved_imports': sum(len(n.unresolved_imports) for n in nodes),
                'cache_hits': cache_hits,
                'timestamp': str(datetime.datetime.now()),
            }
        }
        self._save_parse_cache(next_cache)
        return graph

    def _build_symbol_graph(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        symbol_edges, resolved_counts = self._resolve_symbol_edges(nodes, edges)
        incoming_by_file: Dict[str, int] = defaultdict(int)
        imported_names: Dict[str, int] = defaultdict(int)
        inbound_calls: Dict[str, int] = defaultdict(int)
        outbound_calls: Dict[str, int] = defaultdict(int)
        inbound_calls_local: Dict[str, int] = defaultdict(int)
        outbound_calls_local: Dict[str, int] = defaultdict(int)
        for edge in edges:
            incoming_by_file[edge['target']] += 1
        for edge in symbol_edges:
            if edge.get('kind') == 'calls-symbol':
                inbound_calls[edge['target']] += 1
                outbound_calls[edge['source']] += 1
            elif edge.get('kind') == 'calls-symbol-local':
                inbound_calls_local[edge['target']] += 1
                outbound_calls_local[edge['source']] += 1
                inbound_calls[edge['target']] += 1
                outbound_calls[edge['source']] += 1
            else:
                imported_names[edge['target']] += 1

        symbols: List[Dict[str, Any]] = []
        file_rank = {n.id: n.pagerank or n.importance for n in nodes}
        for node in nodes:
            for sym in node.symbols:
                sid = f"{node.id}::{sym.name}"
                imported = imported_names.get(sid, 0)
                total_inbound = inbound_calls.get(sid, 0)
                rank = file_rank.get(node.id, 0) * 0.50
                rank += (1.0 if sym.exported else 0.0) * 0.20
                rank += min(imported, 5) / 5 * 0.10
                rank += min(total_inbound, 8) / 8 * 0.20
                symbols.append({
                    'id': sid,
                    'name': sym.name,
                    'kind': sym.kind,
                    'file': node.id,
                    'start_line': sym.line,
                    'end_line': sym.end_line or sym.line,
                    'signature': sym.signature,
                    'exported': sym.exported,
                    'rank': round(rank, 6),
                    'role': node.role,
                    'incoming_file_imports': incoming_by_file.get(node.id, 0),
                    'named_imports': imported,
                    'resolved_imports': resolved_counts.get(sid, 0),
                    'inbound_calls': inbound_calls.get(sid, 0),
                    'inbound_calls_local': inbound_calls_local.get(sid, 0),
                    'outbound_calls': outbound_calls.get(sid, 0),
                    'outbound_calls_local': outbound_calls_local.get(sid, 0),
                })
        symbols.sort(key=lambda s: s['rank'], reverse=True)
        return symbols

    def _direct_export_index(self, nodes: List[ProjectNode]) -> Dict[str, Dict[str, str]]:
        index: Dict[str, Dict[str, str]] = defaultdict(dict)
        for node in nodes:
            export_names = set(node.exports)
            if node.id.endswith('.py') and not export_names:
                exported_symbols = [s for s in node.symbols if not s.name.startswith('_')]
            else:
                exported_symbols = [s for s in node.symbols if s.exported or s.name in export_names]
            for sym in exported_symbols:
                sid = f"{node.id}::{sym.name}"
                index[node.id][sym.name] = sid
                if 'default' in export_names and sym.exported:
                    index[node.id].setdefault('default', sid)
            if 'default' in export_names and exported_symbols:
                index[node.id].setdefault('default', f"{node.id}::{exported_symbols[0].name}")
        return index

    def _resolved_export_index(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        exports = {file: dict(names) for file, names in self._direct_export_index(nodes).items()}
        for node in nodes:
            exports.setdefault(node.id, {})
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge.get('kind') != 're-export':
                    continue
                source_file = edge['source']
                target_file = edge['target']
                target_exports = exports.get(target_file, {})
                specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
                for spec in specifiers:
                    imported = spec.get('imported')
                    local = spec.get('local') or imported
                    if imported == '*':
                        for name, sid in target_exports.items():
                            if name not in exports[source_file]:
                                exports[source_file][name] = sid
                                changed = True
                    elif imported in target_exports and exports[source_file].get(local) != target_exports[imported]:
                        exports[source_file][local] = target_exports[imported]
                        changed = True
        return exports

    def _source_symbol_ids(self, node: ProjectNode) -> List[str]:
        exported = [s for s in node.symbols if s.exported]
        chosen = exported or node.symbols[:1]
        return [f"{node.id}::{s.name}" for s in chosen]

    def _symbol_source(self, node: ProjectNode, sym: Symbol, file_cache: Optional[Dict[str, List[str]]] = None) -> str:
        path = os.path.join(self.root, node.id)
        if file_cache is not None and node.id in file_cache:
            lines = file_cache[node.id]
        else:
            content = self.parser.safe_read(path)
            if not content:
                if file_cache is not None:
                    file_cache[node.id] = []
                return ""
            lines = content.splitlines()
            if file_cache is not None:
                file_cache[node.id] = lines
        start = max(1, sym.line)
        end = max(start, sym.end_line or sym.line)
        if end == start and start <= len(lines):
            end = _infer_symbol_end_line(lines, start)
        return "\n".join(lines[start - 1:end])

    def _local_import_targets(self, edge: Dict[str, Any], exports: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
        target_exports = exports.get(edge['target'], {})
        specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
        targets: List[Dict[str, str]] = []
        for spec in specifiers:
            imported = spec.get('imported')
            local = spec.get('local') or imported
            if imported == '*':
                targets.append({'local': local, 'target': '*', 'imported': '*'})
                continue
            target_sid = target_exports.get(imported)
            if target_sid:
                targets.append({'local': local, 'target': target_sid, 'imported': imported})
        return targets

    def _detect_symbol_calls(
        self,
        nodes: List[ProjectNode],
        edges: List[Dict[str, Any]],
        exports: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        node_by_id = {n.id: n for n in nodes}
        symbols_by_file_name: Dict[str, Dict[str, str]] = defaultdict(dict)
        for node in nodes:
            for sym in node.symbols:
                symbols_by_file_name[node.id][sym.name] = f"{node.id}::{sym.name}"

        imports_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            if edge.get('kind') != 'import':
                continue
            imports_by_file[edge['source']].extend(self._local_import_targets(edge, exports))

        call_edges: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, str]] = set()
        file_cache: Dict[str, List[str]] = {}

        for node in nodes:
            local_targets = imports_by_file.get(node.id, [])
            local_symbol_map: Dict[str, str] = {}
            for sym in node.symbols:
                local_symbol_map[sym.name] = f"{node.id}::{sym.name}"

            callable_targets: List[Tuple[str, str, str, bool]] = []
            for target in local_targets:
                local = target.get('local', '')
                if local and local != '*' and target.get('target'):
                    callable_targets.append((local, target['target'], target['target'].split('::', 1)[0], False))
            for sym_name, sym_sid in local_symbol_map.items():
                callable_targets.append((sym_name, sym_sid, node.id, True))

            qualified_targets: Dict[Tuple[str, str], Tuple[str, str, bool]] = {}
            for target in local_targets:
                local = target.get('local', '')
                target_sid = target.get('target', '')
                if not local or not target_sid:
                    continue
                if target_sid == '*':
                    target_file = next(
                        (
                            edge.get('target')
                            for edge in edges
                            if edge.get('source') == node.id
                            and any(spec.get('local') == local and spec.get('imported') == '*' for spec in edge.get('specifiers', []))
                        ),
                        '',
                    )
                else:
                    target_file = target_sid.split('::', 1)[0]
                if not target_file:
                    continue
                for member_name, member_sid in symbols_by_file_name.get(target_file, {}).items():
                    qualified_targets[(local, member_name)] = (member_sid, target_file, False)

            for qualifier_name in local_symbol_map:
                for member_name, member_sid in symbols_by_file_name.get(node.id, {}).items():
                    qualified_targets[(qualifier_name, member_name)] = (member_sid, node.id, True)
            for implicit_receiver in ('self', 'this'):
                for member_name, member_sid in symbols_by_file_name.get(node.id, {}).items():
                    qualified_targets[(implicit_receiver, member_name)] = (member_sid, node.id, True)

            if not callable_targets:
                if not qualified_targets:
                    continue

            for sym in node.symbols:
                source_sid = f"{node.id}::{sym.name}"
                if sym.calls is not None:
                    body_call_names = set()
                    body_qualified_calls = set()
                    for callee in sym.calls:
                        callee = callee.strip()
                        m_qual = re.search(r'\b([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*(?:\.|::)\s*([A-Za-z_]\w*)$', callee)
                        if m_qual:
                            body_qualified_calls.add((m_qual.group(1), m_qual.group(2)))
                        else:
                            m_simple = re.search(r'\b([A-Za-z_]\w*)$', callee)
                            if m_simple:
                                body_call_names.add(m_simple.group(1))
                else:
                    body = self._symbol_source(node, sym, file_cache)
                    if not body:
                        continue
                    body_call_names = set(re.findall(r'\b([A-Za-z_]\w*)\s*\(', body))
                    body_qualified_calls = set(
                        re.findall(r'\b([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*\.\s*([A-Za-z_]\w*)\s*\(', body)
                    )

                for qualifier, member_name in body_qualified_calls:
                    target = qualified_targets.get((qualifier, member_name))
                    if not target:
                        continue
                    target_sid, target_file, is_local = target
                    if target_sid == source_sid:
                        continue
                    key = (source_sid, target_sid, f'{qualifier}.{member_name}')
                    if key not in seen:
                        call_edges.append({
                            'source': source_sid,
                            'target': target_sid,
                            'imported': member_name,
                            'local': f'{qualifier}.{member_name}',
                            'source_file': node.id,
                            'target_file': target_file,
                            'line': sym.line,
                            'kind': 'calls-symbol-local' if is_local else 'calls-symbol',
                            'qualified': True,
                        })
                        seen.add(key)

                for callee_name, target_sid, target_file, is_local in callable_targets:
                    if target_sid == source_sid:
                        continue
                    if callee_name not in body_call_names:
                        continue
                    key = (source_sid, target_sid, callee_name)
                    if key not in seen:
                        call_edges.append({
                            'source': source_sid,
                            'target': target_sid,
                            'imported': callee_name if not is_local else callee_name,
                            'local': callee_name,
                            'source_file': node.id,
                            'target_file': target_file,
                            'line': sym.line,
                            'kind': 'calls-symbol' if not is_local else 'calls-symbol-local',
                        })
                        seen.add(key)
        return call_edges

    def _resolve_symbol_edges(self, nodes: List[ProjectNode], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        node_by_id = {n.id: n for n in nodes}
        exports = self._resolved_export_index(nodes, edges)
        symbol_edges: List[Dict[str, Any]] = []
        resolved_counts: Dict[str, int] = defaultdict(int)
        seen: Set[Tuple[str, str, str]] = set()

        for edge in edges:
            if edge.get('kind') == 're-export':
                continue
            source_node = node_by_id.get(edge['source'])
            if not source_node:
                continue
            source_symbols = self._source_symbol_ids(source_node)
            if not source_symbols:
                continue
            target_exports = exports.get(edge['target'], {})
            specifiers = edge.get('specifiers') or [{'imported': n, 'local': n} for n in edge.get('names', [])]
            if not specifiers:
                continue
            for spec in specifiers:
                imported = spec.get('imported')
                if imported == '*':
                    target_ids = list(target_exports.values())
                else:
                    target = target_exports.get(imported)
                    target_ids = [target] if target else []
                for source_sid in source_symbols:
                    for target_sid in target_ids:
                        key = (source_sid, target_sid, imported or '', spec.get('local', imported) or '')
                        if target_sid and key not in seen:
                            symbol_edges.append({
                                'source': source_sid,
                                'target': target_sid,
                                'imported': imported,
                                'local': spec.get('local', imported),
                                'source_file': edge['source'],
                                'target_file': edge['target'],
                                'line': edge.get('line', 0),
                                'kind': 'imports-symbol',
                            })
                            resolved_counts[target_sid] += 1
                            seen.add(key)
        symbol_edges.extend(self._detect_symbol_calls(nodes, edges, exports))
        return symbol_edges, resolved_counts
