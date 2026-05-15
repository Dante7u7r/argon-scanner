param(
    [switch]$Coverage
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = "1"

python -B -m py_compile argon.py argon_mcp.py argon_view.py argon_watch.py

if ($Coverage) {
    python -m pytest --cov=argon --cov-report=term-missing
} else {
    python -m pytest
}
