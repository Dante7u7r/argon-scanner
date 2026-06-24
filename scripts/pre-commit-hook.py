#!/usr/bin/env python3
"""Parse argon JSON output and find symbols from non-staged files."""
import json
import sys

def main():
    if len(sys.argv) < 3:
        print("Usage: pre-commit-hook.py <json_file> <staged_file1> [staged_file2...]", file=sys.stderr)
        sys.exit(1)
    
    json_file = sys.argv[1]
    staged_files = set(sys.argv[2:])
    
    with open(json_file) as f:
        data = json.load(f)
    
    for s in data.get('symbols', []):
        file_path = s.get('file', '')
        if file_path and file_path not in staged_files:
            print(f'{file_path}::{s.get("name", "")} ({s.get("kind", "")}) tier={s.get("tier", "")} score={s.get("confidence_score", 0):.2f}')

if __name__ == '__main__':
    main()