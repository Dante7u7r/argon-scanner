"""Community detection via greedy modularity optimization (Louvain-inspired)."""

from collections import defaultdict
from typing import Any, Dict, List


def detect_communities(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Group files into communities based on import density.

    Returns dict mapping community label → list of file paths.
    """
    if not edges:
        return {}

    node_ids = {n.get('id', '') for n in nodes}
    adj: Dict[str, set] = defaultdict(set)
    for e in edges:
        src = e.get('source', '')
        dst = e.get('target', '')
        if src in node_ids and dst in node_ids and src != dst:
            adj[src].add(dst)
            adj[dst].add(src)

    if not adj:
        return {}

    communities: Dict[str, str] = {nid: nid for nid in adj}

    changed = True
    while changed:
        changed = False
        for node in adj:
            neigh = adj[node]
            if not neigh:
                continue
            current = communities[node]
            current_score = sum(1 for nb in neigh if communities.get(nb) == current)
            for candidate in {communities.get(nb, nb) for nb in neigh}:
                if candidate == current:
                    continue
                candidate_score = sum(1 for nb in neigh if communities.get(nb) == candidate)
                if candidate_score > current_score:
                    communities[node] = candidate
                    current_score = candidate_score
                    changed = True
                    current = candidate

    groups: Dict[str, List[str]] = defaultdict(list)
    for nid, comm in communities.items():
        groups[comm].append(nid)

    merged: Dict[str, List[str]] = defaultdict(list)
    assigned: set = set()
    for members in sorted(groups.values(), key=len, reverse=True):
        for m in members:
            if m not in assigned:
                merged[members[0]].append(m)
                assigned.add(m)

    result: Dict[str, List[str]] = {}
    for key, members in merged.items():
        if len(members) >= 3:
            label = _infer_label(members)
            result[label] = sorted(members)

    return result


def _infer_label(members: List[str]) -> str:
    """Infer a short label from file paths."""
    parts: defaultdict = defaultdict(int)
    for m in members:
        segs = m.rstrip('/').split('/')
        if len(segs) >= 2:
            parts[segs[-2]] += 1
        if len(segs) >= 1:
            base = segs[-1].rsplit('.', 1)[0]
            if base not in ('index', 'main', '__init__', '__main__'):
                parts[base] += 2
    if parts:
        return max(parts, key=lambda k: parts[k])
    return 'module'
