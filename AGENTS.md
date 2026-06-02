# argon-scanner — AGENTS.md

## For LLM Agents (Claude, Gemini, GPT, local models)

### What ARGON does
ARGON scans a codebase and returns a **token-budgeted context** optimized for LLM consumption. It identifies the most relevant files for a task using keyword matching, PageRank, architectural roles, git hotspots, and dependency analysis.

### Recommended flow
```
1. argon_overview()         → Project stats, file types, connectivity hubs
2. argon_focused_context()  → Files most relevant to your task (budgeted)
3. argon_expand_symbol()    → Deep-dive into a symbol with code + relationships
4. argon_smart_start()      → Check if project has relevant code before spending tokens
```

### Output format guide
Use `--format compact` for maximum token efficiency (58% less tokens than JSON):

```
!table.py::_calculate_column_widths|cri|func|hub|0.48
  < table.py::Table              ← called by Table (direct)
  << export.py::print_table      ←← called transitively by print_table
  >> table.py::render_row        →→ transitively calls render_row
  sig: def _calculate_column_widths(self, console, options)
  code:
      def _calculate_column_widths(...)
```

**Symbol legend:**
- `!id|tier|kind|role|confidence` — tier=crt/wkf/sup, role=hub/api/entr/leaf/util
- `>` = calls, `<` = called by, `>>` = transitively calls, `<<` = transitively called by
- `+` = imports, `sig:` = function/class signature, `code:` = source code
- `#` = metadata lines (repo info, modules, debt, test coverage)

**Confidence labels:** very_high (≥0.65), high (≥0.35), medium (≥0.10), low (<0.10)
- very_high/high: read the code. These are the most relevant symbols.
- medium: skim. May be useful context.
- low: ignore unless you need more context.

**Relationships between symbols:** The `<`, `>`, `<<`, `>>` markers show the call graph within the selected context. If token.ts::validateToken appears as `<` of auth.ts::authenticate, then authenticate calls validateToken.

**Expansion plan:** `# expansion:` at the bottom lists next-best symbols to read if budget allows. Use `argon_expand_symbol()` to get full code for any of them.

### Quick decisions for LLM agents
- **Budget < 2000 tokens:** Use `argon_smart_start()` first. If it says "relevant", use `argon_focused_context()` with max_tokens=1500 and `--format compact`.
- **Task mentions "fix bug":** The tool will find recently-changed files (git hotspot) and test counterparts.
- **Task mentions "add feature":** Look at `# modules:` in compact output to understand the architecture before diving into code.
- **Task mentions "refactor":** Check `# debt:` for high-severity markers (FIXME, BUG, XXX) in relevant modules.

---

## For Developers (contributing)

### Entry points
- `argon/main.py:main` — CLI (`python -m argon . --precision --task "..." --format compact`)
- `argon_mcp.py` — MCP server (19 tools, ArgonMCPServer class)
- `argon_watch.py` — File watcher with incremental rebuild and delta reports
- `run_argon.py` — Wrapper without pip install

### CLI
```bash
# Precision mode (real token counting with tiktoken)
python -m argon . --precision --task "fix auth bug" --budget 4096 --format compact

# Budget profiles
python -m argon . --precision --task "..." --budget-profile micro   # 1500 tokens
                                              --budget-profile deep   # 8192 tokens

# Output formats: xml, json, markdown, compact
python -m argon . --precision --task "..." --format compact
```

### Architecture
- **Parser:** Dual tree-sitter (100+ languages) + regex fallback (`argon/parser/`)
- **Resolvers:** tsconfig paths, Composer PSR-4, Python absolute/relative, C# projects (`argon/resolvers/`)
- **Engine:** BuilderMixin → ArgonEngine → selector → formatter (`argon/engine/`)
- **Scoring:** task keywords × PageRank × architectural roles × git hotspots × personalized PageRank × mutual information
- **Cache:** `.argon_cache.json` (gitignored, mtime-invalidated)

### Key mathematical components
- `_personalized_pagerank()` — topic-sensitive PageRank with task-biased teleport
- `score_symbol_for_task()` — keywords × IDF × information content × structural signals
- `select_precision_symbols()` — MMR diversity + greedy value-per-token budget

### Tests
```bash
pytest                                  # all tests (139)
pytest tests/test_unit.py               # unit tests
pytest tests/test_precision_engine.py   # precision mode tests
```

### Generated files (gitignored)
`ARGON.*`, `ARGON_PRECISION.*`, `argon_graph.json`, `argon_view.html`, `ARGON_DELTA.md`

### Lint/typecheck
- `ruff check .` / `ruff format .`
- `mypy .`

### Dependencies
- `tree-sitter` + `tree-sitter-language-pack` (Rust via FFI, 100+ languages)
- `tiktoken` (Rust via FFI, real token counting)
- `watchdog` (file watching)
- `mcp` (MCP server protocol)
- Optional: `sentence-transformers` (~2GB, semantic search)
