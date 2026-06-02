#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
python -B -m py_compile argon.py argon_mcp.py argon_view.py argon_watch.py
python -m pytest "${@}"
