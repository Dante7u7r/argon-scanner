from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any


@dataclass
class Symbol:
    name: str
    kind: str
    line: int
    end_line: int = 0
    summary: str = ""
    signature: str = ""
    exported: bool = False
    calls: Optional[List[str]] = None


@dataclass
class ProjectNode:
    id: str
    type: str
    lines: int = 0
    size_bytes: int = 0
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    import_records: List[Dict[str, Any]] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    unresolved_imports: List[str] = field(default_factory=list)
    resolved_imports: Dict[str, str] = field(default_factory=dict)
    summary: str = ""
    importance: float = 0.0
    pagerank: float = 0.0
    role: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
