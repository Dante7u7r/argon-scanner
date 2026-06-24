# IDE Integration Guide

## PyCharm / IntelliJ / WebStorm / CLion / Rider (JetBrains IDEs)

### External Tool Configuration

1. Open **Settings/Preferences** → **Tools** → **External Tools**
2. Click **+** to add a new tool:

#### ARGON Precision Scan (Current File)
```
Name: ARGON Precision Scan
Description: Scan for related symbols using ARGON
Program: argon
Arguments: --precision --task "$Prompt$" $FilePath$ --budget 2048 --format compact
Working directory: $ProjectFileDir$
```

#### ARGON Context Report (Whole Project)
```
Name: ARGON Context Report
Description: Generate markdown context report
Program: argon
Arguments: --context --budget 2048
Working directory: $ProjectFileDir$
```

3. Assign keyboard shortcuts (optional): **Settings** → **Keymap** → **External Tools** → **ARGON Precision Scan**

### Usage
- Right-click a file → **External Tools** → **ARGON Precision Scan**
- Enter task description (e.g., "fix authentication bug")
- Output opens in a tool window

---

## VS Code

### Task Configuration (`.vscode/tasks.json`)
```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "ARGON: Precision Scan",
      "type": "shell",
      "command": "argon",
      "args": [
        "--precision",
        "--task",
        "${input:argonTask}",
        "--budget",
        "2048",
        "--format",
        "compact"
      ],
      "problemMatcher": [],
      "group": "build",
      "presentation": {
        "reveal": "always",
        "panel": "new"
      }
    },
    {
      "label": "ARGON: Context Report",
      "type": "shell",
      "command": "argon",
      "args": ["--context", "--budget", "2048"],
      "problemMatcher": [],
      "group": "build"
    }
  ],
  "inputs": [
    {
      "id": "argonTask",
      "type": "promptString",
      "description": "Task description (e.g., 'fix auth bug')",
      "default": "review changes"
    }
  ]
}
```

### Keybinding (`.vscode/keybindings.json`)
```json
{
  "key": "ctrl+shift+a",
  "command": "workbench.action.tasks.runTask",
  "args": "ARGON: Precision Scan"
}
```

### Usage
- `Ctrl+Shift+P` → **Tasks: Run Task** → **ARGON: Precision Scan**
- Enter task description
- Output in terminal panel

---

## Git Pre-commit Hook

### Automatic (pre-commit.com)
```bash
pip install pre-commit
pre-commit install
# Copies .pre-commit-config.yaml hooks to .git/hooks/
```

### Manual
```bash
cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Behavior
- Runs on `git commit`
- Analyzes staged files
- Warns about potentially related files not in the commit
- **Advisory only** (exit 0) — won't block commits
- Set `ARGON_PRECOMMIT_VERBOSE=1` for debug output

### Configuration
```bash
# Custom argon binary
export ARGON_CMD=/path/to/argon

# Custom token budget
export BUDGET=4096

# Verbose output
export ARGON_PRECOMMIT_VERBOSE=1
```

---

## Command Line Quick Reference

```bash
# Precision mode (task-aware, token-budgeted)
argon . --precision --task "fix auth bug" --budget 4096 --format compact

# Context mode (full project overview)
argon . --context --budget 2048

# Budget profiles
argon . --precision --task "..." --budget-profile micro   # 1500 tokens
argon . --precision --task "..." --budget-profile deep    # 8192 tokens

# Output formats
argon . --precision --task "..." --format xml
argon . --precision --task "..." --format json
argon . --precision --task "..." --format markdown

# Visualize
argon . --precision --task "..." --view
argon . --precision --task "..." --open-view
```

---

## MCP Server (Claude Desktop, Cline, etc.)

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

Available tools: `argon_overview`, `argon_focused_context`, `argon_expand_symbol`, `argon_smart_start`, `argon_graph_stats`, `argon_find_symbol`, `argon_search_code`, `argon_git_hotspots`, `argon_debt_report`, `argon_test_gaps`, `argon_dependencies`, `argon_communities`, `argon_symbol_neighbors`, `argon_file_summary`, `argon_project_domain`, `argon_expand_plan`, `argon_context_report`, `argon_precision_context`, `argon_watch_start`, `argon_watch_stop`, `argon_watch_status`

---

## File Watcher (Continuous Updates)

```bash
# Start watcher (daemon)
argon-watch .

# In another terminal: check status
argon-watch . --status

# Stop
argon-watch . --stop
```

Outputs `ARGON_DELTA.md` on changes — perfect for live context in long-running sessions.