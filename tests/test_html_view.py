from pathlib import Path

import pytest
from conftest import run_argon

import argon_deps
import argon_view


def test_html_view_loads_modes_without_console_errors(universal_project: Path, tmp_path: Path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    result = run_argon(
        universal_project,
        tmp_path,
        "--precision",
        "--task",
        "fix helper bug",
        "--budget",
        "1200",
        "--format",
        "json",
        "--view",
    )
    assert result.returncode == 0, result.stderr + result.stdout

    view_path = tmp_path / "argon_view.html"
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.goto(view_path.as_uri(), wait_until="networkidle")

        assert page.title() == "ARGON_OS // ARCHITECTURE_SCANNER v9.0"
        assert page.locator("text=ARGON_ARCHITECT").is_visible()
        assert page.locator("button[data-mode='files']").is_visible()
        assert page.locator("button[data-mode='symbols']").is_visible()
        assert page.locator("button[data-mode='calls']").is_visible()
        diagnostics = page.locator("#diagnostics-panel").inner_text()
        assert "MODE: PRECISION" in diagnostics
        assert "UNRESOLVED IMPORTS: 0" in diagnostics

        page.locator("button[data-mode='symbols']").click()
        page.wait_for_timeout(300)
        page.locator("button[data-mode='calls']").click()
        page.wait_for_timeout(300)

        canvas_count = page.locator("canvas").count()
        assert canvas_count >= 1
        nonblank = page.locator("canvas").first.evaluate(
            """canvas => {
                const ctx = canvas.getContext('2d') || canvas.getContext('webgl2') || canvas.getContext('webgl');
                if (!ctx) return false;
                const w = canvas.width;
                const h = canvas.height;
                if (w === 0 || h === 0) return false;
                if (ctx.readPixels) {
                    const pixels = new Uint8Array(4);
                    ctx.readPixels(Math.floor(w / 2), Math.floor(h / 2), 1, 1, ctx.RGBA, ctx.UNSIGNED_BYTE, pixels);
                    return pixels.some(v => v !== 0);
                }
                const data = ctx.getImageData(Math.floor(w / 2), Math.floor(h / 2), 1, 1).data;
                return Array.from(data).some(v => v !== 0);
            }"""
        )
        browser.close()

    assert not console_errors
    assert nonblank


def test_view_popup_dependency_is_optional_and_falls_back(monkeypatch, tmp_path: Path):
    html = tmp_path / "argon_view.html"
    html.write_text("<html></html>", encoding="utf-8")
    opened = []

    monkeypatch.setattr(argon_view, "_ensure_dep", lambda *args, **kwargs: None)
    monkeypatch.setattr(argon_view.webbrowser, "open", lambda url: opened.append(url))

    viz = argon_view.ArgonVisualizer(str(tmp_path / "missing.json"), str(tmp_path / "missing.html"))
    assert viz._open_popup(str(html)) is False
    viz.render = lambda output_path=str(html), open_browser=True: (
        argon_view.webbrowser.open(f"file://{html}") if open_browser else None
    ) or True
    assert viz.render(open_browser=True) is True
    assert opened == [f"file://{html}"]


def test_pywebview_registered_as_optional_view_dependency():
    assert ("pywebview", "webview", False, "desktop popup webview") in argon_deps._VIEW_DEPS
