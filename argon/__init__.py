"""
ARGON v9.0 // UNIVERSAL ARCHITECTURE SCANNER

Dual parser: Tree-sitter (AST) con fallback a regex mejorado.
Token budget system para consumo optimo por IAs.
"""

from argon_deps import ensure as _ensure_dep

# Tree-sitter bootstrap (auto-install if missing)
ts_pack = None
try:
    import tree_sitter_language_pack as ts_pack
    from tree_sitter_language_pack import get_language
    from tree_sitter_language_pack import get_parser as ts_get_parser
except ImportError:
    _ts_core = _ensure_dep("tree-sitter", "tree_sitter", description="AST parser core")
    _ts_pack = _ensure_dep("tree-sitter-language-pack", "tree_sitter_language_pack", description="AST language grammars")
    if _ts_pack is not None:
        ts_pack = _ts_pack
        from tree_sitter_language_pack import get_language
        from tree_sitter_language_pack import get_parser as ts_get_parser
    else:
        try:
            from tree_sitter_languages import get_language
            from tree_sitter_languages import get_parser as ts_get_parser
        except ImportError:
            pass

# tiktoken
tiktoken = _ensure_dep("tiktoken", "tiktoken", description="real token counting")

# pathspec
pathspec = _ensure_dep("pathspec", "pathspec", description="gitignore parser")

from argon.engine.graph import ArgonEngine
from argon.models import ProjectNode, Symbol
from argon.parser import UniversalParser
from argon.resolvers.composer import ComposerResolver
from argon.resolvers.ignore import IgnoreMatcher
from argon.resolvers.imports import ImportResolver
from argon.resolvers.tsconfig import TsConfigResolver
from argon.utils.noise import STDLIB_NOISE, SYMBOL_NOISE
from argon.utils.tokens import PRECISION_BUDGET_PROFILES, TokenCounter, estimate_tokens, resolve_precision_budget
