#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static Laravel adapter for Argon.

This adapter intentionally avoids mutating commands. It reads Laravel structure,
routes, migrations and logs so MCP clients can reason about a Laravel app safely.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List


_ROUTE_RE = re.compile(
    r"Route::(?P<method>get|post|put|patch|delete|resource|apiResource|match|any)\s*\((?P<body>.*?)\)\s*;",
    re.S,
)
_CONTROLLER_RE = re.compile(r"([A-Za-z_][\w\\]*Controller)::class")
_MIGRATION_RE = re.compile(r"Schema::(?:create|table)\(['\"](?P<table>[^'\"]+)['\"]")


def is_laravel_project(root: str) -> bool:
    root_path = Path(root)
    composer = root_path / "composer.json"
    artisan = root_path / "artisan"
    if not composer.exists() or not artisan.exists():
        return False
    try:
        data = json.loads(composer.read_text(encoding="utf-8"))
    except Exception:
        return False
    packages = {**data.get("require", {}), **data.get("require-dev", {})}
    return "laravel/framework" in packages


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def laravel_overview(root: str) -> Dict[str, Any]:
    root_path = Path(root)
    composer_path = root_path / "composer.json"
    composer: Dict[str, Any] = {}
    if composer_path.exists():
        try:
            composer = json.loads(composer_path.read_text(encoding="utf-8"))
        except Exception:
            composer = {}
    require = composer.get("require", {})
    return {
        "detected": is_laravel_project(root),
        "laravel_version": require.get("laravel/framework", "unknown"),
        "php_version": require.get("php", "unknown"),
        "controllers": len(list((root_path / "app" / "Http" / "Controllers").rglob("*.php"))) if (root_path / "app").exists() else 0,
        "models": len(list((root_path / "app" / "Models").rglob("*.php"))) if (root_path / "app" / "Models").exists() else 0,
        "migrations": len(list((root_path / "database" / "migrations").glob("*.php"))) if (root_path / "database" / "migrations").exists() else 0,
        "route_files": [_rel(root_path, p) for p in (root_path / "routes").glob("*.php")] if (root_path / "routes").exists() else [],
    }


def laravel_routes(root: str) -> List[Dict[str, Any]]:
    root_path = Path(root)
    routes_dir = root_path / "routes"
    out: List[Dict[str, Any]] = []
    if not routes_dir.exists():
        return out
    for path in routes_dir.glob("*.php"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ROUTE_RE.finditer(text):
            body = match.group("body")
            uri_match = re.search(r"['\"]([^'\"]+)['\"]", body)
            controllers = _CONTROLLER_RE.findall(body)
            out.append({
                "file": _rel(root_path, path),
                "method": match.group("method").upper(),
                "uri": uri_match.group(1) if uri_match else "",
                "controllers": controllers,
            })
    return out


def laravel_schema(root: str) -> List[Dict[str, Any]]:
    root_path = Path(root)
    migrations = root_path / "database" / "migrations"
    out: List[Dict[str, Any]] = []
    if not migrations.exists():
        return out
    for path in sorted(migrations.glob("*.php")):
        text = path.read_text(encoding="utf-8", errors="replace")
        tables = _MIGRATION_RE.findall(text)
        columns = re.findall(r"\$table->(?P<type>\w+)\(['\"](?P<name>[^'\"]+)['\"]", text)
        out.append({
            "file": _rel(root_path, path),
            "tables": tables,
            "columns": [{"type": typ, "name": name} for typ, name in columns],
        })
    return out


def laravel_recent_errors(root: str, max_lines: int = 80) -> Dict[str, Any]:
    log_path = Path(root) / "storage" / "logs" / "laravel.log"
    if not log_path.exists():
        return {"file": None, "lines": []}
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    error_lines = [line for line in lines if "ERROR" in line or "Exception" in line]
    return {
        "file": "storage/logs/laravel.log",
        "lines": error_lines[-max_lines:],
    }
