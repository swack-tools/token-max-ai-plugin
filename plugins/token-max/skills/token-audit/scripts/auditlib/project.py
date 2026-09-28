"""Inventory candidate context costs; do not pretend file size proves waste."""
import ast
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess

from .measure import digest

EXCLUDED = {'.git', '.github_examples', '.firecrawl', '.token-audit', '.venv',
            'venv', 'node_modules', '__pycache__', 'target', 'dist', 'build', 'vendor'}
INSTRUCTIONS = {'AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'AGNETS.md'}
SECRET = re.compile(r'(^\.env($|\.)|credentials|secrets?|id_rsa|id_ed25519|\.pem$|\.key$)', re.I)
ROUTING = re.compile(r'\b(model|routing|route|gpt[- ]?\d|claude|sonnet|haiku|opus)\b', re.I)


def inventory(root):
    commands = [(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], 'git'),
                (['rg', '--files', '--hidden', '--no-require-git', '-0', str(root)], 'rg')]
    for command, method in commands:
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            names = result.stdout.decode('utf-8', errors='replace').split('\0')
            return sorted({root / name for name in names if name}), method
    raise ValueError('Project enumeration requires Git in a repository or ripgrep (rg).')


def function_sizes(text, path, meter):
    if path.suffix != '.py':
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return []
    lines = text.splitlines(keepends=True)
    return [{'path': str(path), 'name': node.name, 'line': node.lineno,
             'end_line': node.end_lineno,
             **meter.measure(''.join(lines[node.lineno - 1:node.end_lineno]))}
            for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def instruction_info(text, row):
    positions = defaultdict(list)
    for number, line in enumerate(text.splitlines(), 1):
        normalized = line.strip()
        if len(normalized) >= 40:
            positions[digest(normalized)].append(number)
    return {**row, 'routing_lines': [n for n, line in enumerate(text.splitlines(), 1) if ROUTING.search(line)][:30],
            'duplicate_lines': [ns for ns in positions.values() if len(ns) > 1][:20],
            'typo_candidate': Path(row['path']).name == 'AGNETS.md',
            'activation': 'unverified; inspect applicable hierarchy/config and session evidence'}


def analyze_project(root, meter, extra_instructions=(), max_bytes=1_000_000, excluded_paths=()):
    root = root.resolve()
    paths, method = inventory(root)
    files, functions, instructions, warnings = [], [], [], []
    excluded = Counter()
    languages = Counter()
    extra = {Path(p).expanduser().absolute() for p in extra_instructions}
    generated = {Path(p).resolve() for p in excluded_paths}
    for path in sorted(set(paths) | extra):
        if path.resolve() in generated:
            excluded['audit_report'] += 1
            continue
        is_extra = path in extra
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        if path.is_symlink() or (not is_extra and (not path.resolve().is_relative_to(root)
                or set(relative.parts) & EXCLUDED)):
            excluded['excluded_or_symlink'] += 1
            continue
        if SECRET.search(path.name):
            excluded['secret_filename'] += 1
            continue
        try:
            size = path.stat().st_size
            if size > max_bytes:
                excluded['over_size_limit'] += 1
                continue
            data = path.read_bytes()
            if b'\0' in data:
                excluded['binary'] += 1
                continue
            text = data.decode('utf-8')
        except (OSError, UnicodeError):
            excluded['unreadable_or_non_utf8'] += 1
            continue
        row = {'path': str(relative), 'sha256': digest(text), **meter.measure(text)}
        if is_extra:
            row['path'] = str(path)
        else:
            files.append(row)
            languages[path.suffix or '(no extension)'] += 1
            functions.extend(function_sizes(text, relative, meter))
        if path.name in INSTRUCTIONS or is_extra:
            instructions.append(instruction_info(text, row))
    if excluded['over_size_limit']:
        warnings.append('Files above the byte limit were skipped; inventory is incomplete.')
    return {'root': str(root), 'inventory_method': method, 'files_scanned': len(files),
            'max_file_bytes': max_bytes, 'excluded_counts': dict(excluded),
            'extensions': dict(languages.most_common()),
            'files': sorted(files, key=lambda row: row['bytes'], reverse=True),
            'functions': sorted(functions, key=lambda row: row['lines'], reverse=True)[:30],
            'instructions': sorted(instructions, key=lambda row: row['bytes'], reverse=True),
            'warnings': warnings,
            'limits': ['Inventory is current disk state, which may differ from the session revision.',
                       'Python functions use AST spans; other languages have file-level measurements only.',
                       'Large files, routing lines, and duplicate lines are review candidates, not proven waste.',
                       'Ignored/generated/vendor/secret-named files and symlinks are excluded.',
                       'CLAUDE.md/AGNETS.md presence does not establish that Codex loads them.']}
