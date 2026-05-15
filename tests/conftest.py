import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ARGON = ROOT / "argon.py"
ARGON_MCP = ROOT / "argon_mcp.py"


@pytest.fixture
def universal_project(tmp_path: Path) -> Path:
    project = tmp_path / "universal_project"
    project.mkdir()

    (project / ".gitignore").write_text("ignored_assets/\n*.tmp\n", encoding="utf-8")
    (project / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {"@core/*": ["ts/src/core/*"]},
                }
            }
        ),
        encoding="utf-8",
    )

    ts_core = project / "ts" / "src" / "core"
    ts_core.mkdir(parents=True)
    (ts_core / "helper.ts").write_text(
        "export function helper(value: string) {\n"
        "  return value.toUpperCase();\n"
        "}\n",
        encoding="utf-8",
    )
    (project / "ts" / "src" / "main.ts").write_text(
        "import { helper } from '@core/helper';\n"
        "export function runMain() {\n"
        "  return helper('argon');\n"
        "}\n",
        encoding="utf-8",
    )

    py_pkg = project / "py" / "pkg"
    py_pkg.mkdir(parents=True)
    (py_pkg / "__init__.py").write_text("", encoding="utf-8")
    (py_pkg / "helper.py").write_text(
        "def py_helper(value: str) -> str:\n"
        "    return value.upper()\n",
        encoding="utf-8",
    )
    (py_pkg / "main.py").write_text(
        "from .helper import py_helper\n\n"
        "def run_py() -> str:\n"
        "    return py_helper('argon')\n",
        encoding="utf-8",
    )

    java_src = project / "java" / "src"
    java_src.mkdir(parents=True)
    (java_src / "Main.java").write_text(
        "class Main {\n"
        "  String run() { return \"argon\"; }\n"
        "}\n",
        encoding="utf-8",
    )

    ignored = project / "ignored_assets"
    ignored.mkdir()
    (ignored / "noise.ts").write_text("export const ignored = true;\n", encoding="utf-8")
    (project / "scratch.tmp").write_text("temporary\n", encoding="utf-8")

    return project


@pytest.fixture
def monorepo_project(tmp_path: Path) -> Path:
    project = tmp_path / "monorepo_project"
    project.mkdir()

    (project / ".gitignore").write_text("dist/\n.cache/\n", encoding="utf-8")
    (project / "package.json").write_text(
        json.dumps({"private": True, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    (project / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@app/*": ["packages/app/src/*"],
                        "@shared/*": ["packages/shared/src/*"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    shared = project / "packages" / "shared" / "src"
    shared.mkdir(parents=True)
    (shared / "math.ts").write_text(
        "export function sumPrice(a: number, b: number) {\n"
        "  return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    (shared / "index.ts").write_text(
        "export * from './math';\n",
        encoding="utf-8",
    )

    app = project / "packages" / "app" / "src"
    app.mkdir(parents=True)
    (app / "checkout.ts").write_text(
        "import { sumPrice } from '@shared/index';\n\n"
        "export function checkoutTotal(items: number[]) {\n"
        "  return items.reduce((total, item) => sumPrice(total, item), 0);\n"
        "}\n",
        encoding="utf-8",
    )
    (app / "checkout.test.ts").write_text(
        "import { checkoutTotal } from './checkout';\n\n"
        "export function testCheckoutTotal() {\n"
        "  return checkoutTotal([1, 2]) === 3;\n"
        "}\n",
        encoding="utf-8",
    )
    (project / "packages" / "app" / "tsconfig.json").write_text(
        json.dumps({"extends": "../../tsconfig.json"}),
        encoding="utf-8",
    )

    py_pkg = project / "services" / "billing" / "billing"
    py_pkg.mkdir(parents=True)
    (py_pkg / "__init__.py").write_text("", encoding="utf-8")
    (py_pkg / "money.py").write_text(
        "def normalize_money(value: int) -> int:\n"
        "    return max(value, 0)\n",
        encoding="utf-8",
    )
    (py_pkg / "invoice.py").write_text(
        "from billing.money import normalize_money\n\n"
        "def invoice_total(value: int) -> int:\n"
        "    return normalize_money(value)\n",
        encoding="utf-8",
    )

    dist = project / "dist"
    dist.mkdir()
    (dist / "bundle.ts").write_text("export const bundled = true;\n", encoding="utf-8")

    return project


@pytest.fixture
def laravel_project(tmp_path: Path) -> Path:
    project = tmp_path / "laravel_project"
    project.mkdir()
    (project / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
    (project / "composer.json").write_text(
        json.dumps(
            {
                "require": {"php": "^8.2", "laravel/framework": "^12.0"},
                "autoload": {"psr-4": {"App\\": "app/"}},
            }
        ),
        encoding="utf-8",
    )

    controller_dir = project / "app" / "Http" / "Controllers"
    model_dir = project / "app" / "Models"
    routes_dir = project / "routes"
    migration_dir = project / "database" / "migrations"
    log_dir = project / "storage" / "logs"
    for path in (controller_dir, model_dir, routes_dir, migration_dir, log_dir):
        path.mkdir(parents=True)

    (model_dir / "Order.php").write_text(
        "<?php\n"
        "namespace App\\Models;\n\n"
        "class Order {\n"
        "  public function total() { return 42; }\n"
        "}\n",
        encoding="utf-8",
    )
    (controller_dir / "OrderController.php").write_text(
        "<?php\n"
        "namespace App\\Http\\Controllers;\n\n"
        "use App\\Models\\Order;\n\n"
        "class OrderController {\n"
        "  public function show() { return (new Order())->total(); }\n"
        "}\n",
        encoding="utf-8",
    )
    (routes_dir / "web.php").write_text(
        "<?php\n"
        "use App\\Http\\Controllers\\OrderController;\n\n"
        "Route::get('/orders/{order}', [OrderController::class, 'show']);\n",
        encoding="utf-8",
    )
    (migration_dir / "2026_01_01_000000_create_orders_table.php").write_text(
        "<?php\n"
        "Schema::create('orders', function ($table) {\n"
        "  $table->id();\n"
        "  $table->string('status');\n"
        "  $table->integer('total');\n"
        "});\n",
        encoding="utf-8",
    )
    (log_dir / "laravel.log").write_text(
        "[2026-01-01] local.ERROR: Order failure Exception\n",
        encoding="utf-8",
    )
    return project


def run_argon(project: Path, output: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(ARGON), str(project), "--output", str(output), *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
