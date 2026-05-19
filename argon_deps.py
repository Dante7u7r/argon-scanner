#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGON DEPENDENCY MANAGER (JIT Auto-Bootstrap)
---------------------------------------------
Ensures all required dependencies are available at runtime.
If a dependency is missing, it is installed automatically via pip.
Uses ONLY stdlib — this module must never have external dependencies.
"""

import importlib
import subprocess
import sys
import os

# Suppress pip's "new version available" noise
os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

# =========================================================================
# DEPENDENCY REGISTRY
# =========================================================================
# (pip_package_name, import_name, is_heavy, description)
_CORE_DEPS = [
    ("pathspec",                   "pathspec",                     False, "gitignore parser"),
    ("tiktoken",                   "tiktoken",                     False, "real token counting"),
    ("tree-sitter",                "tree_sitter",                  False, "AST parser core"),
    ("tree-sitter-language-pack",  "tree_sitter_language_pack",    False, "AST language grammars"),
    ("mcp",                        "mcp",                          False, "MCP server protocol"),
]

_SEMANTIC_DEPS = [
    ("sentence-transformers",      "sentence_transformers",        True,  "semantic embedding AI model (~2GB with PyTorch)"),
]


# =========================================================================
# INSTALLER
# =========================================================================

def _pip_install(package: str, heavy: bool = False, description: str = "") -> bool:
    """Install a package via pip. Returns True on success."""
    label = f"{package}"
    if description:
        label += f" ({description})"

    if heavy:
        print(f"[!] =========================================================", file=sys.stderr)
        print(f"[!]  ARGON TIER-S: Instalando {label}", file=sys.stderr)
        print(f"[!]  ADVERTENCIA: Descarga masiva (>2GB con PyTorch).", file=sys.stderr)
        print(f"[!]  La terminal tardara varios minutos. NO cierres.", file=sys.stderr)
        print(f"[!] =========================================================", file=sys.stderr)
    else:
        print(f"[*] Auto-instalando: {label}...", file=sys.stderr)

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", package],
            stdout=subprocess.DEVNULL if not heavy else None,
            stderr=subprocess.DEVNULL if not heavy else None,
        )
        # Invalidate import caches so the new module can be found
        importlib.invalidate_caches()
        print(f"[+] Instalado: {package}", file=sys.stderr)
        return True
    except subprocess.CalledProcessError:
        print(f"[!] FALLO al instalar {package}. Instala manualmente: pip install {package}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[!] Error inesperado instalando {package}: {e}", file=sys.stderr)
        return False


def ensure(pip_name: str, import_name: str = "", heavy: bool = False, description: str = ""):
    """
    Try to import a module. If it fails, auto-install via pip and retry.
    Returns the imported module on success, or None on failure.
    """
    mod_name = import_name or pip_name
    try:
        return importlib.import_module(mod_name)
    except ImportError:
        pass

    # Not installed — attempt JIT install
    if _pip_install(pip_name, heavy=heavy, description=description):
        try:
            return importlib.import_module(mod_name)
        except ImportError:
            print(f"[!] {pip_name} se instalo pero no se pudo importar '{mod_name}'.", file=sys.stderr)
            return None
    return None


def ensure_core() -> dict:
    """
    Ensure all core dependencies are available.
    Returns a dict of {import_name: module_or_None}.
    """
    results = {}
    for pip_name, import_name, heavy, desc in _CORE_DEPS:
        results[import_name] = ensure(pip_name, import_name, heavy, desc)
    return results


def ensure_semantic() -> dict:
    """
    Ensure semantic (heavy) dependencies are available.
    Returns a dict of {import_name: module_or_None}.
    """
    results = {}
    for pip_name, import_name, heavy, desc in _SEMANTIC_DEPS:
        results[import_name] = ensure(pip_name, import_name, heavy, desc)
    return results
