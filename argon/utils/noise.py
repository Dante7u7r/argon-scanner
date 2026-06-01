import re

STDLIB_NOISE = {
    'os', 're', 'sys', 'json', 'time', 'math', 'random', 'datetime',
    'pathlib', 'typing', 'dataclasses', 'collections', 'itertools',
    'functools', 'io', 'abc', 'enum', 'copy', 'hashlib', 'base64',
    'urllib', 'http', 'threading', 'subprocess', 'shutil', 'glob',
    'argparse', 'logging', 'unittest', 'string', 'struct', 'socket',
    'contextlib', 'traceback', 'inspect', 'ast', 'textwrap', 'uuid',
    'asyncio', 'multiprocessing', 'signal', 'tempfile', 'pickle',
    'csv', 'xml', 'html', 'email', 'sqlite3', 'decimal',
    'fs', 'path', 'crypto', 'events', 'stream', 'util', 'url',
    'https', 'net', 'dns', 'child_process', 'process', 'buffer',
    'assert', 'cluster', 'readline', 'zlib', 'tls',
    'react', 'vue', 'angular', 'svelte', 'express', 'fastapi',
    'flask', 'django', 'fastify', 'axios', 'lodash', 'moment',
    'numpy', 'pandas', 'matplotlib', 'scipy', 'sklearn', 'torch',
    'requests', 'pytest', 'click', 'pydantic', 'sqlalchemy',
    'next', 'nuxt', 'vite', 'webpack', 'babel', 'eslint',
    'tailwindcss', 'prisma', 'mongoose', 'sequelize', 'typeorm',
    'java', 'javax', 'android',
    'fmt', 'strings', 'strconv', 'errors', 'context', 'sync',
    'testing', 'encoding', 'reflect', 'runtime', 'sort', 'bytes',
    'std', 'core', 'alloc', 'tokio', 'serde', 'anyhow', 'clap',
}

SYMBOL_NOISE = {
    'ValueError', 'TypeError', 'RuntimeError', 'Exception', 'Error',
    'Promise', 'Map', 'Set', 'Array', 'Object', 'String', 'Number',
}

_KW_BLACKLIST = frozenset({
    'if', 'else', 'for', 'while', 'switch', 'case', 'return', 'throw',
    'catch', 'try', 'new', 'delete', 'typeof', 'instanceof', 'void',
    'null', 'true', 'false', 'this', 'super', 'import', 'export',
    'from', 'class', 'extends', 'implements', 'interface', 'package',
    'using', 'namespace', 'var', 'let', 'const', 'int', 'string',
    'bool', 'float', 'double', 'long', 'short', 'byte', 'char',
    'boolean', 'object', 'dynamic', 'readonly', 'where', 'select',
})

_DOCSTRING_PATS = [
    re.compile(r'^\s*"""(.+?)"""', re.DOTALL),
    re.compile(r"^\s*'''(.+?)'''", re.DOTALL),
    re.compile(r'^\s*/\*\*?\s*(.+)'),
]

_COMMENT_PATS = [
    re.compile(r'^\s*#\s*(.+)'),
    re.compile(r'^\s*//\s*(.+)'),
    re.compile(r'^\s*\*\s*(.+)'),
    re.compile(r'^\s*--\s*(.+)'),
    re.compile(r'^\s*;\s*(.+)'),
]

IMPORT_EXTS = {
    'py', 'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs',
    'java', 'go', 'rs', 'php', 'rb', 'cs', 'c', 'cpp', 'h', 'hpp',
    'swift', 'kt', 'scala', 'ex', 'exs', 'lua', 'r', 'jl',
    'sh', 'bat', 'ps1',
}
