#!/usr/bin/env python3
"""
ARGON WATCH v9.0 -- MASTER SENTINEL (watchdog-based)
Delegates to argon.watcher.
"""
import sys
import os

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from argon.watcher import main as _main
    _main()


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from argon.watcher import main as _main
    _main()
