#!/usr/bin/env python3
"""Project only requested evidence fields; keep full JSON out of model context."""
import argparse
import json
from pathlib import Path
import sys

FIELDS = {
    'diagnostics': ('session', 'diagnostics', ('line', 'tool', 'signals', 'exit_codes', 'record_sha256')),
    'outputs': ('session', 'tool_outputs', ('line', 'tool', 'bytes', 'text_tokens', 'record_sha256')),
    'repeats': ('session', 'repeated_calls', ('tool', 'count', 'lines')),
    'instructions': ('project', 'instructions', ('path', 'bytes', 'text_tokens', 'routing_lines', 'activation')),
    'files': ('project', 'files', ('path', 'bytes', 'text_tokens')),
    'functions': ('project', 'functions', ('path', 'name', 'line', 'lines')),
}


def select(report, kind, limit=3, offset=0):
    if not 1 <= limit <= 20 or offset < 0:
        raise ValueError('Use limit 1..20 and offset >= 0.')
    section, key, fields = FIELDS[kind]
    rows = (report.get(section) or {}).get(key, [])
    return dict(kind=kind, total=len(rows), offset=offset,
                next_offset=offset + limit if offset + limit < len(rows) else None,
                rows=[{field: row[field] for field in fields if field in row}
                      for row in rows[offset:offset + limit]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--kind', choices=FIELDS, required=True)
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    try:
        result = select(json.loads(args.report.read_text()), args.kind, args.limit, args.offset)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        print(f'token-audit query: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
