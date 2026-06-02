"""Architectural role classification from the import graph."""

from collections import defaultdict
from typing import Any, Dict, List


def classify_file_roles(nodes: List[Any], edges: List[Dict[str, Any]]) -> Dict[str, str]:
    incoming: Dict[str, int] = defaultdict(int)
    outgoing: Dict[str, int] = defaultdict(int)
    for edge in edges:
        src = edge.get('source', '')
        dst = edge.get('target', '')
        if src and dst:
            outgoing[src] += 1
            incoming[dst] += 1

    roles: Dict[str, str] = {}
    for node in nodes:
        nid = node.id
        inc = incoming.get(nid, 0)
        out = outgoing.get(nid, 0)
        has_exports = bool(node.exports)

        if inc > 0 and out == 0:
            roles[nid] = 'leaf'
        elif out > 0 and inc == 0:
            roles[nid] = 'entry_point'
        elif inc >= 3 and out >= 3:
            roles[nid] = 'hub'
        elif inc >= 5 and inc > out * 3:
            roles[nid] = 'api_surface'
        elif out > 0 and inc == 0 and not has_exports:
            roles[nid] = 'utility'
        else:
            roles[nid] = 'module'

    return roles


def role_score_boost(role: str) -> float:
    return {
        'entry_point': 1.30,
        'hub': 1.25,
        'api_surface': 1.20,
        'module': 1.00,
        'leaf': 0.85,
        'utility': 0.75,
        '': 1.00,
    }.get(role, 1.00)
