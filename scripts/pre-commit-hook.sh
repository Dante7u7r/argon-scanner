#!/usr/bin/env bash
# ARGON pre-commit hook
# Detects potentially missed related files based on staged changes.
# Usage: Copy to .git/hooks/pre-commit, or use with pre-commit.com

set -euo pipefail

# Configuration
ARGON_CMD="${ARGON_CMD:-argon}"
BUDGET="${BUDGET:-2048}"
VERBOSE="${ARGON_PRECOMMIT_VERBOSE:-0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

log() {
    [[ "$VERBOSE" == "1" ]] && echo -e "${GREEN}[argon-pre-commit]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[argon-pre-commit] WARNING:${NC} $*"
}

err() {
    echo -e "${RED}[argon-pre-commit] ERROR:${NC} $*"
}

# Check if argon is available
if ! command -v "$ARGON_CMD" &> /dev/null; then
    log "argon not found in PATH, skipping hook"
    exit 0
fi

# Get staged files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|js|ts|tsx|jsx|java|cs|go|rs|cpp|c|h|hpp|rb|php|swift|kt|scala|lua|r|ex|exs|sh|html|css|sql|toml|yaml|yml|json|md)$' || true)

if [[ -z "$STAGED_FILES" ]]; then
    log "No staged source files, skipping"
    exit 0
fi

log "Staged files:"
echo "$STAGED_FILES" | sed 's/^/  /'

# Build task description from staged files
TASK_KEYWORDS=$(echo "$STAGED_FILES" | sed -E 's|.*/||; s/\.[^.]+$//; s/[_-]/ /g' | tr '[:upper:]' '[:lower:]' | tr ' ' '\n' | sort -u | tr '\n' ' ')
TASK="review changes in: $TASK_KEYWORDS"

log "Task: $TASK"

# Run argon in precision mode (outputs JSON to ARGON_PRECISION.json)
"$ARGON_CMD" . --precision --task "$TASK" --budget "$BUDGET" --format json >/dev/null 2>&1 || {
    err "argon command failed."
    exit 0
}

OUTPUT_FILE="ARGON_PRECISION.json"
[[ -f "$OUTPUT_FILE" ]] || {
    err "Could not find argon output file"
    exit 0
}

log "Argon output: $OUTPUT_FILE"

# Parse JSON output for symbols from files NOT in staged list
MISSING=$(python3 "$SCRIPT_DIR/pre-commit-hook.py" "$OUTPUT_FILE" $STAGED_FILES)

if [[ -n "$MISSING" ]]; then
    warn "Potentially related files you may want to review:"
    echo "$MISSING" | head -10 | sed 's/^/  /'
    echo ""
    warn "Run 'argon . --precision --task \"$TASK\" --budget $BUDGET --format json' for full analysis"
fi

# Always exit 0 (advisory only)
exit 0