#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON QUALITY BENCHMARK v1.0
-----------------------------
Formal precision@budget and recall@budget benchmarks for multi-language
symbol selection. Uses fixture projects with known expected results.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argon import ArgonEngine
from argon_bench import score_graph


# =========================================================================
# FIXTURE GENERATOR
# =========================================================================

def create_fixture_typescript(base: Path) -> Path:
    """Create a TypeScript fixture project with barrels, aliases, and tests."""
    project = base / "fixture_ts"
    project.mkdir(exist_ok=True)

    (project / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@lib/*": ["src/lib/*"], "@models/*": ["src/models/*"]},
        }
    }), encoding="utf-8")
    (project / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")

    src = project / "src"
    lib = src / "lib"
    models = src / "models"
    services = src / "services"
    tests = project / "tests"
    for d in (lib, models, services, tests):
        d.mkdir(parents=True, exist_ok=True)

    # Models
    (models / "user.ts").write_text(
        "export interface User {\n"
        "  id: string;\n"
        "  email: string;\n"
        "  name: string;\n"
        "}\n\n"
        "export function createUser(email: string, name: string): User {\n"
        "  return { id: crypto.randomUUID(), email, name };\n"
        "}\n",
        encoding="utf-8",
    )
    (models / "order.ts").write_text(
        "import { User } from './user';\n\n"
        "export interface Order {\n"
        "  id: string;\n"
        "  userId: string;\n"
        "  total: number;\n"
        "}\n\n"
        "export function calculateTotal(items: number[]): number {\n"
        "  return items.reduce((sum, item) => sum + item, 0);\n"
        "}\n",
        encoding="utf-8",
    )
    # Barrel re-export
    (models / "index.ts").write_text(
        "export * from './user';\n"
        "export * from './order';\n",
        encoding="utf-8",
    )

    # Library
    (lib / "auth.ts").write_text(
        "import { User, createUser } from '@models/index';\n\n"
        "export async function authenticate(email: string, password: string): Promise<User | null> {\n"
        "  if (!email || !password) return null;\n"
        "  return createUser(email, 'Authenticated User');\n"
        "}\n\n"
        "export function hashPassword(password: string): string {\n"
        "  return password.split('').reverse().join('');\n"
        "}\n\n"
        "export function validateToken(token: string): boolean {\n"
        "  return token.length > 10;\n"
        "}\n",
        encoding="utf-8",
    )
    (lib / "payment.ts").write_text(
        "import { Order, calculateTotal } from '@models/order';\n\n"
        "export function processPayment(order: Order): { success: boolean; transactionId: string } {\n"
        "  const total = calculateTotal([order.total]);\n"
        "  return { success: total > 0, transactionId: crypto.randomUUID() };\n"
        "}\n\n"
        "export function refundPayment(transactionId: string): boolean {\n"
        "  return transactionId.length > 0;\n"
        "}\n",
        encoding="utf-8",
    )
    (lib / "cache.ts").write_text(
        "const store: Map<string, any> = new Map();\n\n"
        "export function cacheGet(key: string): any {\n"
        "  return store.get(key);\n"
        "}\n\n"
        "export function cacheSet(key: string, value: any, ttl: number = 3600): void {\n"
        "  store.set(key, value);\n"
        "}\n\n"
        "export function cacheInvalidate(key: string): boolean {\n"
        "  return store.delete(key);\n"
        "}\n",
        encoding="utf-8",
    )
    # Barrel
    (lib / "index.ts").write_text(
        "export * from './auth';\n"
        "export * from './payment';\n"
        "export * from './cache';\n",
        encoding="utf-8",
    )

    # Services (internal calls)
    (services / "userService.ts").write_text(
        "import { authenticate, validateToken } from '@lib/auth';\n"
        "import { User } from '@models/user';\n\n"
        "export async function loginUser(email: string, password: string): Promise<User | null> {\n"
        "  return authenticate(email, password);\n"
        "}\n\n"
        "export function checkSession(token: string): boolean {\n"
        "  return validateToken(token);\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "orderService.ts").write_text(
        "import { processPayment, refundPayment } from '@lib/payment';\n"
        "import { Order, calculateTotal } from '@models/order';\n"
        "import { cacheGet, cacheSet } from '@lib/cache';\n\n"
        "export function placeOrder(items: number[]): { orderId: string; paid: boolean } {\n"
        "  const total = calculateTotal(items);\n"
        "  const order: Order = { id: crypto.randomUUID(), userId: 'u1', total };\n"
        "  const result = processPayment(order);\n"
        "  cacheSet(`order:${order.id}`, order);\n"
        "  return { orderId: order.id, paid: result.success };\n"
        "}\n\n"
        "export function cancelOrder(orderId: string, transactionId: string): boolean {\n"
        "  cacheGet(`order:${orderId}`);\n"
        "  return refundPayment(transactionId);\n"
        "}\n",
        encoding="utf-8",
    )

    # Tests
    (tests / "auth.test.ts").write_text(
        "import { authenticate, hashPassword, validateToken } from '@lib/auth';\n\n"
        "export async function testAuthenticate() {\n"
        "  const user = await authenticate('test@example.com', 'password');\n"
        "  return user !== null;\n"
        "}\n\n"
        "export function testHashPassword() {\n"
        "  return hashPassword('abc') === 'cba';\n"
        "}\n",
        encoding="utf-8",
    )
    (tests / "payment.test.ts").write_text(
        "import { processPayment, refundPayment } from '@lib/payment';\n\n"
        "export function testProcessPayment() {\n"
        "  const result = processPayment({ id: '1', userId: 'u1', total: 100 });\n"
        "  return result.success === true;\n"
        "}\n",
        encoding="utf-8",
    )

    return project


def create_fixture_typescript_noisy(base: Path) -> Path:
    """Create a TypeScript fixture where textual search is swamped by distractors."""
    project = base / "fixture_ts_noisy"
    project.mkdir(exist_ok=True)

    (project / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@core/*": ["src/core/*"], "@noise/*": ["src/noise/*"]},
        }
    }), encoding="utf-8")
    (project / ".gitignore").write_text("dist/\nnode_modules/\n", encoding="utf-8")

    core = project / "src" / "core"
    noise = project / "src" / "noise"
    tests = project / "tests"
    for directory in (core, noise, tests):
        directory.mkdir(parents=True, exist_ok=True)

    (core / "session.ts").write_text(
        "export interface Session {\n"
        "  userId: string;\n"
        "  token: string;\n"
        "}\n\n"
        "export function loadSession(token: string): Session | null {\n"
        "  if (!token) return null;\n"
        "  return { userId: 'u1', token };\n"
        "}\n",
        encoding="utf-8",
    )
    (core / "authFlow.ts").write_text(
        "import { loadSession, Session } from './session';\n\n"
        "export function validateLoginToken(token: string): boolean {\n"
        "  return token.length > 10;\n"
        "}\n\n"
        "export function resolveAuthenticatedUser(token: string): Session | null {\n"
        "  if (!validateLoginToken(token)) return null;\n"
        "  return loadSession(token);\n"
        "}\n",
        encoding="utf-8",
    )
    (tests / "authFlow.test.ts").write_text(
        "import { resolveAuthenticatedUser, validateLoginToken } from '@core/authFlow';\n\n"
        "export function testResolveAuthenticatedUser() {\n"
        "  return resolveAuthenticatedUser('very-long-token') !== null;\n"
        "}\n\n"
        "export function testValidateLoginToken() {\n"
        "  return validateLoginToken('very-long-token') === true;\n"
        "}\n",
        encoding="utf-8",
    )

    for index in range(18):
        (noise / f"authNoise{index}.ts").write_text(
            f"export function authenticateNoise{index}(token: string): boolean {{\n"
            f"  return token.includes('auth-{index}');\n"
            "}\n\n"
            f"export function loginNoise{index}(userId: string): string {{\n"
            f"  return `login-noise-{index}:${{userId}}`;\n"
            "}\n\n"
            f"export function sessionNoise{index}(sessionId: string): string {{\n"
            f"  return `session-noise-{index}:${{sessionId}}`;\n"
            "}\n",
            encoding="utf-8",
        )

    return project


def create_fixture_python(base: Path) -> Path:
    """Create a Python fixture project with packages, relative imports, and tests."""
    project = base / "fixture_python"
    project.mkdir(exist_ok=True)
    (project / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\n", encoding="utf-8")

    pkg = project / "app"
    models = pkg / "models"
    services = pkg / "services"
    utils = pkg / "utils"
    tests = project / "tests"
    for d in (models, services, utils, tests):
        d.mkdir(parents=True, exist_ok=True)

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (models / "__init__.py").write_text(
        "from .user import User, create_user\n"
        "from .order import Order, calculate_total\n",
        encoding="utf-8",
    )
    (models / "user.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class User:\n"
        "    id: str\n"
        "    email: str\n"
        "    name: str\n\n"
        "def create_user(email: str, name: str) -> User:\n"
        "    import uuid\n"
        "    return User(id=str(uuid.uuid4()), email=email, name=name)\n",
        encoding="utf-8",
    )
    (models / "order.py").write_text(
        "from dataclasses import dataclass\n"
        "from typing import List\n\n"
        "@dataclass\n"
        "class Order:\n"
        "    id: str\n"
        "    user_id: str\n"
        "    total: float\n\n"
        "def calculate_total(items: List[float]) -> float:\n"
        "    return sum(items)\n",
        encoding="utf-8",
    )
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "auth_service.py").write_text(
        "from ..models.user import User, create_user\n\n"
        "def authenticate(email: str, password: str) -> User:\n"
        "    if not email or not password:\n"
        "        raise ValueError('Invalid credentials')\n"
        "    return create_user(email, 'Auth User')\n\n"
        "def hash_password(password: str) -> str:\n"
        "    return password[::-1]\n\n"
        "def validate_token(token: str) -> bool:\n"
        "    return len(token) > 10\n",
        encoding="utf-8",
    )
    (services / "order_service.py").write_text(
        "from ..models.order import Order, calculate_total\n"
        "from ..utils.cache import cache_get, cache_set\n\n"
        "def place_order(items: list) -> dict:\n"
        "    total = calculate_total(items)\n"
        "    order = Order(id='o1', user_id='u1', total=total)\n"
        "    cache_set(f'order:{order.id}', order)\n"
        "    return {'order_id': order.id, 'total': total}\n\n"
        "def cancel_order(order_id: str) -> bool:\n"
        "    cached = cache_get(f'order:{order_id}')\n"
        "    return cached is not None\n",
        encoding="utf-8",
    )
    (utils / "__init__.py").write_text("", encoding="utf-8")
    (utils / "cache.py").write_text(
        "_store: dict = {}\n\n"
        "def cache_get(key: str):\n"
        "    return _store.get(key)\n\n"
        "def cache_set(key: str, value, ttl: int = 3600):\n"
        "    _store[key] = value\n\n"
        "def cache_invalidate(key: str) -> bool:\n"
        "    return _store.pop(key, None) is not None\n",
        encoding="utf-8",
    )
    (tests / "test_auth.py").write_text(
        "from app.services.auth_service import authenticate, hash_password\n\n"
        "def test_authenticate():\n"
        "    user = authenticate('test@example.com', 'password')\n"
        "    assert user.email == 'test@example.com'\n\n"
        "def test_hash_password():\n"
        "    assert hash_password('abc') == 'cba'\n",
        encoding="utf-8",
    )
    (tests / "test_order.py").write_text(
        "from app.services.order_service import place_order, cancel_order\n\n"
        "def test_place_order():\n"
        "    result = place_order([10.0, 20.0, 30.0])\n"
        "    assert result['total'] == 60.0\n",
        encoding="utf-8",
    )

    return project


def create_fixture_java(base: Path) -> Path:
    """Create a Java fixture project with packages and interfaces."""
    project = base / "fixture_java"
    project.mkdir(exist_ok=True)
    (project / ".gitignore").write_text("build/\n*.class\n", encoding="utf-8")

    src = project / "src" / "main" / "java" / "com" / "app"
    models = src / "models"
    services = src / "services"
    for d in (models, services):
        d.mkdir(parents=True, exist_ok=True)

    (models / "User.java").write_text(
        "package com.app.models;\n\n"
        "public class User {\n"
        "    private String id;\n"
        "    private String email;\n"
        "    private String name;\n\n"
        "    public User(String id, String email, String name) {\n"
        "        this.id = id;\n"
        "        this.email = email;\n"
        "        this.name = name;\n"
        "    }\n\n"
        "    public String getEmail() { return email; }\n"
        "    public String getName() { return name; }\n"
        "}\n",
        encoding="utf-8",
    )
    (models / "Order.java").write_text(
        "package com.app.models;\n\n"
        "public class Order {\n"
        "    private String id;\n"
        "    private String userId;\n"
        "    private double total;\n\n"
        "    public Order(String id, String userId, double total) {\n"
        "        this.id = id;\n"
        "        this.userId = userId;\n"
        "        this.total = total;\n"
        "    }\n\n"
        "    public double getTotal() { return total; }\n\n"
        "    public static double calculateTotal(double[] items) {\n"
        "        double sum = 0;\n"
        "        for (double item : items) sum += item;\n"
        "        return sum;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "AuthService.java").write_text(
        "package com.app.services;\n\n"
        "import com.app.models.User;\n\n"
        "public class AuthService {\n"
        "    public User authenticate(String email, String password) {\n"
        "        if (email == null || password == null) return null;\n"
        "        return new User(\"1\", email, \"Auth User\");\n"
        "    }\n\n"
        "    public boolean validateToken(String token) {\n"
        "        return token != null && token.length() > 10;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "OrderService.java").write_text(
        "package com.app.services;\n\n"
        "import com.app.models.Order;\n\n"
        "public class OrderService {\n"
        "    public Order placeOrder(double[] items) {\n"
        "        double total = Order.calculateTotal(items);\n"
        "        return new Order(\"o1\", \"u1\", total);\n"
        "    }\n\n"
        "    public boolean cancelOrder(String orderId) {\n"
        "        return orderId != null;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "PaymentService.java").write_text(
        "package com.app.services;\n\n"
        "import com.app.models.Order;\n\n"
        "public interface PaymentService {\n"
        "    boolean processPayment(Order order);\n"
        "    boolean refundPayment(String transactionId);\n"
        "}\n",
        encoding="utf-8",
    )

    return project


def create_fixture_csharp(base: Path) -> Path:
    """Create a C# fixture project with namespaces and interfaces."""
    project = base / "fixture_csharp"
    project.mkdir(exist_ok=True)
    (project / ".gitignore").write_text("bin/\nobj/\n", encoding="utf-8")

    models = project / "Models"
    services = project / "Services"
    for d in (models, services):
        d.mkdir(parents=True, exist_ok=True)

    (models / "User.cs").write_text(
        "namespace App.Models\n"
        "{\n"
        "    public class User\n"
        "    {\n"
        "        public string Id { get; set; }\n"
        "        public string Email { get; set; }\n"
        "        public string Name { get; set; }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (models / "Order.cs").write_text(
        "namespace App.Models\n"
        "{\n"
        "    public class Order\n"
        "    {\n"
        "        public string Id { get; set; }\n"
        "        public string UserId { get; set; }\n"
        "        public decimal Total { get; set; }\n\n"
        "        public static decimal CalculateTotal(decimal[] items)\n"
        "        {\n"
        "            decimal sum = 0;\n"
        "            foreach (var item in items) sum += item;\n"
        "            return sum;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "AuthService.cs").write_text(
        "using App.Models;\n\n"
        "namespace App.Services\n"
        "{\n"
        "    public class AuthService\n"
        "    {\n"
        "        public User Authenticate(string email, string password)\n"
        "        {\n"
        "            if (string.IsNullOrEmpty(email)) return null;\n"
        "            return new User { Id = \"1\", Email = email, Name = \"Auth User\" };\n"
        "        }\n\n"
        "        public bool ValidateToken(string token)\n"
        "        {\n"
        "            return !string.IsNullOrEmpty(token) && token.Length > 10;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (services / "OrderService.cs").write_text(
        "using App.Models;\n\n"
        "namespace App.Services\n"
        "{\n"
        "    public class OrderService\n"
        "    {\n"
        "        public Order PlaceOrder(decimal[] items)\n"
        "        {\n"
        "            var total = Order.CalculateTotal(items);\n"
        "            return new Order { Id = \"o1\", UserId = \"u1\", Total = total };\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    return project


# =========================================================================
# BENCHMARK SPECS (expected results for known tasks)
# =========================================================================

BENCHMARK_SPECS: Dict[str, List[Dict[str, Any]]] = {
    "fixture_ts": [
        {
            "task": "fix authentication bug when user logs in",
            "must_include_ids": [
                "src/lib/auth.ts::authenticate",
                "src/services/userService.ts::loginUser",
                "src/lib/auth.ts::validateToken",
                "src/lib/auth.ts::hashPassword",
            ],
            "must_include_critical_ids": [
                "src/lib/auth.ts::authenticate",
                "src/services/userService.ts::loginUser",
                "src/lib/auth.ts::validateToken",
                "src/lib/auth.ts::hashPassword",
            ],
            "expected_top_symbols": ["authenticate", "loginUser", "validateToken", "hashPassword"],
            "forbidden_top_symbols": ["cacheGet", "calculateTotal", "refundPayment"],
            "max_tokens": 3000,
            "top_n": 10,
        },
        {
            "task": "add refund support to order cancellation",
            "must_include_ids": [
                "src/services/orderService.ts::cancelOrder",
                "src/lib/payment.ts::refundPayment",
                "src/lib/payment.ts::processPayment",
                "src/services/orderService.ts::placeOrder",
            ],
            "must_include_critical_ids": [
                "src/services/orderService.ts::cancelOrder",
                "src/lib/payment.ts::refundPayment",
                "src/lib/payment.ts::processPayment",
                "src/services/orderService.ts::placeOrder",
            ],
            "expected_top_symbols": ["cancelOrder", "refundPayment", "processPayment", "placeOrder"],
            "forbidden_top_symbols": ["authenticate", "hashPassword"],
            "max_tokens": 3000,
            "top_n": 10,
        },
        {
            "task": "optimize cache invalidation strategy",
            "must_include_ids": [
                "src/lib/cache.ts::cacheInvalidate",
                "src/lib/cache.ts::cacheGet",
                "src/lib/cache.ts::cacheSet",
            ],
            "must_include_critical_ids": [
                "src/lib/cache.ts::cacheInvalidate",
                "src/lib/cache.ts::cacheGet",
                "src/lib/cache.ts::cacheSet",
            ],
            "expected_top_symbols": ["cacheInvalidate", "cacheGet", "cacheSet"],
            "forbidden_top_symbols": ["authenticate", "hashPassword", "User"],
            "max_tokens": 3000,
            "top_n": 10,
        },
    ],
    "fixture_ts_noisy": [
        {
            "task": "fix authenticated user resolution when login token is invalid",
            "must_include_ids": [
                "src/core/authFlow.ts::resolveAuthenticatedUser",
                "src/core/authFlow.ts::validateLoginToken",
                "src/core/session.ts::loadSession",
            ],
            "must_include_critical_ids": [
                "src/core/authFlow.ts::resolveAuthenticatedUser",
                "src/core/authFlow.ts::validateLoginToken",
                "src/core/session.ts::loadSession",
            ],
            "expected_top_symbols": ["resolveAuthenticatedUser", "validateLoginToken", "loadSession"],
            "forbidden_top_symbols": ["authenticateNoise", "loginNoise", "sessionNoise"],
            "max_tokens": 2500,
            "top_n": 10,
        },
    ],
    "fixture_python": [
        {
            "task": "fix user authentication when email is empty",
            "must_include_ids": [
                "app/services/auth_service.py::authenticate",
                "app/models/user.py::create_user",
                "app/models/user.py::User",
            ],
            "must_include_critical_ids": [
                "app/services/auth_service.py::authenticate",
            ],
            "expected_top_symbols": ["authenticate", "create_user", "User"],
            "forbidden_top_symbols": ["cache_invalidate", "calculate_total"],
            "max_tokens": 3000,
            "top_n": 10,
        },
        {
            "task": "fix order placement with wrong total calculation",
            "must_include_ids": [
                "app/services/order_service.py::place_order",
                "app/models/order.py::calculate_total",
                "app/models/order.py::Order",
            ],
            "must_include_critical_ids": [
                "app/services/order_service.py::place_order",
                "app/models/order.py::calculate_total",
            ],
            "expected_top_symbols": ["place_order", "calculate_total", "Order"],
            "forbidden_top_symbols": ["authenticate", "hash_password"],
            "max_tokens": 3000,
            "top_n": 10,
        },
    ],
    "fixture_java": [
        {
            "task": "add email validation to authentication",
            "must_include_ids": [
                "src/main/java/com/app/services/AuthService.java::authenticate",
                "src/main/java/com/app/models/User.java::User",
                "src/main/java/com/app/services/AuthService.java::AuthService",
            ],
            "must_include_critical_ids": [
                "src/main/java/com/app/services/AuthService.java::authenticate",
            ],
            "expected_top_symbols": ["authenticate", "User", "AuthService"],
            "forbidden_top_symbols": ["cancelOrder", "OrderService"],
            "max_tokens": 3000,
            "top_n": 10,
        },
    ],
    "fixture_csharp": [
        {
            "task": "fix order total calculation with empty items",
            "must_include_ids": [
                "Models/Order.cs::CalculateTotal",
                "Services/OrderService.cs::PlaceOrder",
                "Models/Order.cs::Order",
            ],
            "must_include_critical_ids": [
                "Models/Order.cs::CalculateTotal",
                "Services/OrderService.cs::PlaceOrder",
            ],
            "expected_top_symbols": ["CalculateTotal", "PlaceOrder", "Order"],
            "forbidden_top_symbols": ["Authenticate", "ValidateToken"],
            "max_tokens": 3000,
            "top_n": 10,
        },
    ],
}


# =========================================================================
# SCORING
# =========================================================================

def score_case(graph: Dict[str, Any], root_dir: str, spec: Dict[str, Any], model: str = "gpt-4.1") -> Dict[str, Any]:
    """Score a single benchmark case against the graph."""
    return score_graph(graph, root_dir, spec, model=model)


def run_all_benchmarks(base_dir: str, model: str = "gpt-4.1") -> Dict[str, Any]:
    """Run all benchmark suites. Creates fixtures if needed."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    creators = {
        "fixture_ts": create_fixture_typescript,
        "fixture_ts_noisy": create_fixture_typescript_noisy,
        "fixture_python": create_fixture_python,
        "fixture_java": create_fixture_java,
        "fixture_csharp": create_fixture_csharp,
    }

    all_results: Dict[str, Any] = {}
    total_score = 0
    total_cases = 0
    total_lift = 0.0
    total_precision_lift = 0.0
    total_budget_utilization = 0.0
    total_guardrails = 0

    for fixture_name, specs in BENCHMARK_SPECS.items():
        creator = creators.get(fixture_name)
        if not creator:
            continue
        project_path = creator(base)
        engine = ArgonEngine(str(project_path), precision=True, model=model)
        graph = engine.build_graph()

        case_results = []
        for spec in specs:
            result = score_case(graph, str(project_path), spec, model)
            case_results.append(result)
            total_score += result["score"]
            total_lift += result.get("recall_lift_vs_best_baseline", 0.0)
            total_precision_lift += result.get("precision_lift_vs_best_baseline", 0.0)
            audit = result.get("context_audit", {})
            total_budget_utilization += audit.get("budget_utilization") or 0.0
            if audit.get("guardrails_ok"):
                total_guardrails += 1
            total_cases += 1

        avg = sum(r["score"] for r in case_results) / max(1, len(case_results))
        all_results[fixture_name] = {
            "project": fixture_name,
            "average_score": round(avg, 4),
            "stats": graph["stats"],
            "cases": case_results,
        }

    overall = total_score / max(1, total_cases)
    return {
        "overall_score": round(overall, 4),
        "average_recall_lift_vs_best_baseline": round(total_lift / max(1, total_cases), 4),
        "average_precision_lift_vs_best_baseline": round(total_precision_lift / max(1, total_cases), 4),
        "average_budget_utilization": round(total_budget_utilization / max(1, total_cases), 4),
        "guardrail_pass_rate": round(total_guardrails / max(1, total_cases), 4),
        "total_cases": total_cases,
        "suites": all_results,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="ARGON Quality Benchmark v1.0")
    parser.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), "tests", "fixtures"),
                        help="Directory to create fixture projects")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--min-score", type=float, default=0.7, help="Minimum passing score")
    args = parser.parse_args()

    print("[*] ARGON Quality Benchmark v1.0")
    print(f"[*] Fixtures: {args.output_dir}")
    print()

    results = run_all_benchmarks(args.output_dir, model=args.model)

    for suite_name, suite in results["suites"].items():
        print(f"\n{'='*60}")
        print(f"  {suite_name.upper()} — avg: {suite['average_score']:.4f}")
        print(f"  Files: {suite['stats']['total_files']} | Symbols: {suite['stats']['total_symbols']} | "
              f"Calls: {suite['stats']['total_symbol_calls']}")
        print(f"{'='*60}")
        for case in suite["cases"]:
            status = "OK" if case["score"] >= args.min_score else "FAIL"
            print(
                f"  {status} [{case['score']:.2f}] {case['task']} "
                f"recall@budget={case.get('recall_at_budget', 0):.2f} "
                f"critical_recall={case.get('critical_recall', 0):.2f} "
                f"precision@top={case.get('precision_at_top', 0):.2f} "
                f"precision@critical={case.get('precision_at_critical', 0):.2f} "
                f"recall_lift={case.get('recall_lift_vs_best_baseline', 0):+.2f} "
                f"precision_lift={case.get('precision_lift_vs_best_baseline', 0):+.2f}"
            )
            baselines = case.get("baselines", {})
            if baselines:
                bits = [
                    f"{name}:recall={data.get('recall_at_top', 0):.2f}"
                    for name, data in baselines.items()
                ]
                print(f"     Baselines: {' | '.join(bits)}")
            if case["expected_missing"]:
                print(f"     MISSING: {', '.join(case['expected_missing'])}")
            if case["forbidden_found"]:
                print(f"     FORBIDDEN: {', '.join(case['forbidden_found'])}")
            if case.get("context_tokens") is not None:
                budget_str = "OK" if case["budget_ok"] else "OVER"
                audit = case.get("context_audit", {})
                print(
                    f"     Budget: {case['context_tokens']} tokens [{budget_str}] "
                    f"util={audit.get('budget_utilization', 0):.2f} "
                    f"context_recall={audit.get('context_required_recall', 0):.2f} "
                    f"reachable_recall={audit.get('required_reachable_recall', 0):.2f} "
                    f"guardrails={'OK' if audit.get('guardrails_ok') else 'WARN'}"
                )

    print(f"\n{'='*60}")
    print(f"  OVERALL: {results['overall_score']:.4f} ({results['total_cases']} cases)")
    print(f"  AVG LIFT vs best baseline: {results['average_recall_lift_vs_best_baseline']:+.4f}")
    print(f"  AVG PRECISION LIFT vs best baseline: {results['average_precision_lift_vs_best_baseline']:+.4f}")
    print(f"  AVG BUDGET UTILIZATION: {results['average_budget_utilization']:.4f}")
    print(f"  GUARDRAIL PASS RATE: {results['guardrail_pass_rate']:.4f}")
    passed = results["overall_score"] >= args.min_score
    print(f"  {'PASS' if passed else 'FAIL'} (min: {args.min_score})")
    print(f"{'='*60}")

    # Save detailed results
    results_path = os.path.join(args.output_dir, "benchmark_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Results: {results_path}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
