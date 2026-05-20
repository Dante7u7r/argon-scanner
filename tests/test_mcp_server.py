import os
import sys
from pathlib import Path

import anyio
import pytest

mcp = pytest.importorskip("mcp")
ClientSession = mcp.ClientSession
StdioServerParameters = mcp.StdioServerParameters
stdio_client = pytest.importorskip("mcp.client.stdio").stdio_client

from conftest import ARGON_MCP, ROOT


def _tool_text(result) -> str:
    return "\n".join(getattr(item, "text", "") for item in result.content)


def test_mcp_stdio_rescan_and_precision_context(universal_project: Path):
    async def scenario():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ARGON_MCP)],
            cwd=str(universal_project),
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}

                assert "argon_rescan" in tool_names
                assert "argon_precision_context" in tool_names

                rescan = await session.call_tool(
                    "argon_rescan",
                    {
                        "project_path": ".",
                        "precision": True,
                        "task": "fix helper bug",
                        "max_tokens": 1200,
                        "output_format": "json",
                    },
                )
                rescan_text = _tool_text(rescan)
                assert "Precision: True" in rescan_text
                assert "Unresolved: 0" in rescan_text

                context = await session.call_tool(
                    "argon_precision_context",
                    {
                        "task_description": "fix helper bug",
                        "max_tokens": 1200,
                        "model": "gpt-4.1",
                    },
                )
                context_text = _tool_text(context)
                assert '"precision": true' in context_text
                assert "helper" in context_text.lower()
                assert '"expansion_plan"' in context_text

                overview = await session.call_tool("argon_overview", {"max_tokens": 1200})
                assert "PROJECT:" in _tool_text(overview)

                query = await session.call_tool("argon_query", {"symbol": "helper", "max_tokens": 1200})
                assert "helper" in _tool_text(query).lower()

                deps = await session.call_tool("argon_deps", {"file_path": "main.ts", "max_tokens": 1200})
                deps_text = _tool_text(deps)
                assert "ts/src/main.ts" in deps_text
                assert "ts/src/core/helper.ts" in deps_text

                search = await session.call_tool("argon_search", {"keyword": "helper", "max_tokens": 1200})
                assert "helper" in _tool_text(search).lower()

                related = await session.call_tool("argon_find_related", {"query": "helper", "max_tokens": 1200})
                assert "related" in _tool_text(related)

                callees = await session.call_tool("argon_trace_callees", {"symbol": "runMain", "max_tokens": 1200})
                assert "helper" in _tool_text(callees).lower()

                symbol_context = await session.call_tool(
                    "argon_context_for_symbol",
                    {"symbol": "helper", "max_tokens": 1200},
                )
                assert "toUpperCase" in _tool_text(symbol_context)

    try:
        anyio.run(scenario)
    except BaseExceptionGroup as exc:
        pytest.fail(str(exc))


def test_mcp_stdio_laravel_adapter_tools(laravel_project: Path):
    async def scenario():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ARGON_MCP)],
            cwd=str(laravel_project),
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(
                    "argon_rescan",
                    {"project_path": ".", "precision": True, "task": "fix order route", "max_tokens": 1200},
                )
                overview = await session.call_tool("argon_framework_overview", {"max_tokens": 1200})
                assert '"detected": true' in _tool_text(overview)
                routes = await session.call_tool("argon_laravel_routes", {"max_tokens": 1200})
                assert "/orders/{order}" in _tool_text(routes)
                schema = await session.call_tool("argon_laravel_schema", {"max_tokens": 1200})
                assert "orders" in _tool_text(schema)
                errors = await session.call_tool("argon_recent_errors", {"max_tokens": 1200})
                assert "Order failure" in _tool_text(errors)

    try:
        anyio.run(scenario)
    except BaseExceptionGroup as exc:
        pytest.fail(str(exc))


def test_mcp_stdio_reports_missing_graph(tmp_path: Path):
    async def scenario():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ARGON_MCP)],
            cwd=str(tmp_path),
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                overview = await session.call_tool("argon_overview", {"max_tokens": 512})
                assert "Grafo no disponible" in _tool_text(overview)

    try:
        anyio.run(scenario)
    except BaseExceptionGroup as exc:
        pytest.fail(str(exc))


def test_mcp_stdio_classic_rescan_uses_non_precision_fallback(universal_project: Path):
    async def scenario():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ARGON_MCP)],
            cwd=str(universal_project),
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                rescan = await session.call_tool(
                    "argon_rescan",
                    {
                        "project_path": ".",
                        "precision": False,
                        "task": "general understanding",
                        "max_tokens": 1200,
                        "output_format": "json",
                    },
                )
                assert "Precision: False" in _tool_text(rescan)

                focused = await session.call_tool(
                    "argon_focused_context",
                    {
                        "task_description": "helper",
                        "max_tokens": 1200,
                    },
                )
                focused_text = _tool_text(focused)
                assert "FOCUSED CONTEXT" in focused_text
                assert "helper" in focused_text.lower()

    try:
        anyio.run(scenario)
    except BaseExceptionGroup as exc:
        pytest.fail(str(exc))
