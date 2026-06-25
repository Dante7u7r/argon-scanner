# ARGON — Token-Budgeted Architecture Context Engine

> **Pre-1.0 static context engine for AI coding assistants.** Scans repositories, ranks symbols, resolves dependencies, and emits task-focused context that fits a strict token budget.

ARGON is a **pure static analysis engine** — no embedded ML models, no LLM calls at scan time. It uses tree-sitter AST parsing, heuristic ranking (PageRank, architectural roles, keyword scoring), and dependency resolution to find the smallest useful slice of a codebase for a specific task.

---

## Architecture

```
argon/
├── parser/           # Dual parser: tree-sitter (100+ languages) + regex fallback
│   ├── tree_sitter.py # AST walk, call queries, scope tracking
│   └── regex.py       # Regex fallback for unsupported languages
├── engine/            # BuilderMixin → ArgonEngine → selector → formatter
│   ├── builder.py     # Graph construction, import resolution, call detection
│   ├── graph.py       # ArgonEngine orchestrator
│   ├── selector.py    # Budget-aware symbol selection (MMR + PageRank)
│   ├── scorer.py      # Keyword × IDF × structural scoring
│   ├── formatter.py   # Output: XML, JSON, Markdown, Compact
│   └── roles.py       # File role classification (hub/api/leaf/entr/util)
├── resolvers/         # Import resolution per ecosystem
│   ├── imports.py     # Cross-file import edge solver
│   ├── python.py      # Absolute/relative Python imports
│   ├── typescript.py  # tsconfig paths + barrel resolution
│   ├── php.py         # Composer PSR-4
│   └── csharp.py      # C# project references
└── models.py          # Symbol, ProjectNode dataclasses
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Tree-sitter > regex** | AST understands structure (nested functions, arrow fns, methods). Regex misses ~85% of symbols in complex files. |
| **`child_by_field_name()` over `.query()`** | `tree_sitter_language_pack` v1.9.1 doesn't expose native query execution (ABI incompatibility). Field-name matching emulates S-expression queries. See `CALL_QUERIES` in `tree_sitter.py`. |
| **Scope tracking** | Call stack maintained during AST walk — each function's calls are collected within its own scope, enabling precise `caller→callee` edges. |
| **PageRank + keyword scoring > embedding search** | Lighter, deterministic, no GPU/download. Sentence-transformers is optional for semantic search. |

### Call Detection Pipeline

1. **Parse** with tree-sitter per language
2. **Walk** AST tracking scope stack (current function/class)
3. **Query** via field-name matching against patterns defined in `CALL_QUERIES`
4. **Emit** edges in graph: `source` (caller) → `target` (callee) with kind `calls-symbol` / `calls-symbol-local`

---

## CLI Usage

```bash
# Scan project (context report)
python -m argon.main /path/to/project --context

# Precision mode (task-aware, token-budgeted)
python -m argon.main . --precision --task "fix auth bug" --budget 4096 --format compact

# Budget profiles
python -m argon.main . --precision --task "..." --budget-profile micro    # 1500 tokens
python -m argon.main . --precision --task "..." --budget-profile standard  # 4096 tokens
python -m argon.main . --precision --task "..." --budget-profile deep      # 8192 tokens

# Output formats
python -m argon.main . --precision --task "..." --format xml       # XML
python -m argon.main . --precision --task "..." --format json      # JSON
python -m argon.main . --precision --task "..." --format markdown  # Markdown
python -m argon.main . --precision --task "..." --format compact   # 58% less tokens than JSON

# Visualization
python -m argon.main . --precision --task "..." --view             # Generate HTML
python -m argon.main . --precision --task "..." --open-view        # Generate + open browser
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `path` | `.` | Project directory to scan |
| `--context` | off | Generate ARGON.md + argon_graph.json |
| `--precision` | off | Precision mode: real tokens, gitignore, PageRank |
| `--task` | `""` | Task description for symbol selection |
| `--model` | `gpt-4.1` | Tokenizer model for budget counting |
| `--format` | `xml` | Output format: xml, json, markdown, compact |
| `--budget` | `4096` | Token budget for context output |
| `--budget-profile` | `custom` | Preset: micro (1500), standard (4096), deep (8192) |
| `--compact` | off | Compact JSON (symbols summarized) |
| `--view` / `--open-view` | off | Generate / open HTML visualization |
| `--output` | project root | Output directory |

---

## Tools

| Command | Description |
|---------|-------------|
| `python -m argon.main` | Universal scanner (tree-sitter + regex) |
| `python argon_view.py` | Interactive HTML visualization (D3.js SVG / PixiJS WebGL) |
| `python argon_mcp.py` | MCP server (19 tools for Claude, Cline, etc.) |
| `python argon_watch.py` | File watcher with delta reports |
| `python argon_semantic.py` | Semantic search via sentence-transformers (optional) |
| `python argon_optimize.py --gate` | Recall gate benchmark (51 cases, anti-regression) |
| `python argon_bench.py` | Custom benchmark runner |
| `python argon_quality_bench.py` | Formal recall@budget / precision@top benchmarks |
| `python argon_deps.py` | Dependency analysis |
| `python argon_ci.py` | CI quality gates |

### MCP Server Tools

`argon_mcp.py` exposes 19 tools for AI assistants: `argon_overview`, `argon_focused_context`, `argon_expand_symbol`, `argon_smart_start`, `argon_graph_stats`, `argon_find_symbol`, `argon_search_code`, `argon_git_hotspots`, `argon_debt_report`, `argon_test_gaps`, `argon_dependencies`, `argon_communities`, `argon_symbol_neighbors`, `argon_file_summary`, `argon_project_domain`, `argon_context_report`, `argon_precision_context`, `argon_watch_start/stop/status`.

Configure in Claude Desktop / Cline:

```json
{
  "mcpServers": {
    "argon": {
      "command": "argon-mcp",
      "args": []
    }
  }
}
```

---

## Language Support

Languages parsed via tree-sitter (fallback to regex when grammar unavailable):

| Language | Extensions | Symbol Kinds |
|----------|-----------|--------------|
| Python | `.py` | function, class |
| TypeScript | `.ts`, `.tsx` | function, class, interface, method |
| JavaScript | `.js`, `.jsx` | function, class, method |
| Rust | `.rs` | function, struct, enum, trait, impl |
| Java | `.java` | method, class, interface, enum, constructor |
| C# | `.cs` | method, class, interface, enum, struct |
| Go | `.go` | function, method, type |
| C/C++ | `.c`, `.h`, `.cpp`, `.hpp` | function, class/struct, enum |
| Ruby | `.rb` | method, class, module |
| PHP | `.php` | function, class, method |
| Kotlin | `.kt` | function, class, object |
| Swift | `.swift` | function, class, struct, protocol |
| Scala | `.scala` | function, class |
| Lua | `.lua` | function |
| R | `.r` | function |
| Elixir | `.ex`, `.exs` | function |
| Shell | `.sh` | function |
| Vue | `.vue` | mapped to TypeScript parser |
| HTML/CSS | `.html`, `.css` | structure |
| SQL/TOML/YAML/JSON | `.sql`, `.toml`, `.yaml`, `.yml`, `.json` | structure |

---

## Output Format (Compact)

The `--format compact` mode emits symbol-level context at ~58% less tokens than JSON:

```
!table.py::_calculate_column_widths|cri|func|hub|0.48
  < table.py::Table              ← called by Table (direct)
  << export.py::print_table      ←← called transitively by print_table
  >> table.py::render_row        →→ transitively calls render_row
  sig: def _calculate_column_widths(self, console, options)
  code:
      def _calculate_column_widths(...)
```

**Symbol legend:** `!id|tier|kind|role|confidence` — tier: cri/wkf/sup, role: hub/api/entr/leaf/util. `>` = calls, `<` = called by, `+` = imports.

### Confidence Labels

| Label | Threshold | Action |
|-------|-----------|--------|
| very_high | ≥0.65 | Read the code |
| high | ≥0.35 | Read the code |
| medium | ≥0.10 | Skim |
| low | <0.10 | Ignore unless needed |

---

## Benchmark & Recall Gate

ARGON includes a recall gate with **51 benchmark cases** across 7 language fixtures:

```bash
# Run gate (anti-regression check)
python argon_optimize.py --gate

# Re-initialize baseline after intentional changes
python argon_optimize.py --gate-init
```

**Current baseline:** aggregate recall `0.8725`

| Fixture | Recall | Files | Symbols |
|---------|--------|-------|---------|
| Python | 1.0000 | 11 | 18 |
| TypeScript | 0.9167 | 11 | 21 |
| Rust | 1.0000 | 11 | 36 |
| Java | 1.0000 | 5 | 20 |
| C# | 1.0000 | 4 | 13 |
| FastAPI | 0.6898 | 19 | 105 |
| Tauri | 0.9697 | 16 | 57 |

### Custom Benchmarks

```bash
# Run against a custom spec
python argon_bench.py /path/to/project benchmark.json --min-score 0.8

# Quality benchmarks
python argon_quality_bench.py --output-dir ./bench --min-score 0.7
```

---

## IDE Integration

### VS Code

Tasks in `.vscode/tasks.json` — `Ctrl+Shift+P` → **Tasks: Run Task** → **ARGON: Precision Scan**. Keybinding: `Ctrl+Shift+A`.

### JetBrains (PyCharm, IntelliJ, WebStorm, etc.)

External tool in **Settings → Tools → External Tools**. Right-click file → **External Tools → ARGON Precision Scan**.

### Pre-commit Hook

```bash
pip install pre-commit && pre-commit install
# Or manual: cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
```

Advisory only — warns about related files not in commit, exits 0.

See `docs/IDE_INTEGRATION.md` for full configuration examples.

---

## Development

### Setup

```bash
git clone <repo>
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pip install tree-sitter-language-pack  # optional, 2MB
```

### Tests

```bash
pytest                           # all tests (138)
pytest tests/test_unit.py        # unit tests
pytest tests/test_scope.py       # scope tracking tests
pytest tests/test_precision_engine.py  # precision mode tests
```

### Lint / Typecheck

```bash
ruff check . && ruff format .    # lint
mypy .                           # type check
```

### Entry Points

- `argon.main:main` — CLI scanner
- `argon_mcp:main` — MCP server
- `argon_view:main` — HTML visualizer
- `argon_watch:main` — File watcher

---

## Generated Files (gitignored)

`ARGON.*`, `ARGON_PRECISION.*`, `argon_graph.json`, `argon_view.html`, `ARGON_DELTA.md`

---

## License

MIT