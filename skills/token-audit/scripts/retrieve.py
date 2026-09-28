#!/usr/bin/env python3
"""Read one fingerprint-verified local tool output, bounded and explicitly untrusted."""
import argparse
import json
from pathlib import Path
import sys

from auditlib.diagnostics import output_text, signals
from auditlib.measure import digest


def retrieve(path, line_number, fingerprint, max_chars=4000, offset=0):
    if line_number < 1 or not 1 <= max_chars <= 16000 or offset < 0:
        raise ValueError('Use line >= 1, max-chars 1..16000, offset >= 0.')
    with path.open(encoding='utf-8', errors='replace') as stream:
        for number, raw in enumerate(stream, 1):
            if number != line_number:
                continue
            row = json.loads(raw)
            payload = row.get('payload') if isinstance(row, dict) else None
            if (row.get('type') if isinstance(row, dict) else None) != 'response_item' or not isinstance(payload, dict):
                raise ValueError('Selected line is not a tool response.')
            if payload.get('type') not in ('function_call_output', 'custom_tool_call_output'):
                raise ValueError('Selected line is not a tool output.')
            if digest(json.dumps(payload, sort_keys=True)) != fingerprint:
                raise ValueError('Evidence changed or wrong log/line; collect fresh evidence.')
            text = output_text(payload.get('output'))
            if offset > len(text):
                raise ValueError('Offset exceeds output length.')
            end = min(len(text), offset + max_chars)
            return dict(line=number, record_sha256=fingerprint, untrusted_evidence=True,
                        **signals(payload.get('output'), text), offset=offset, total_chars=len(text),
                        truncated=offset > 0 or end < len(text),
                        next_offset=end if end < len(text) else None, text=text[offset:end])
    raise ValueError('Selected line is absent; collect fresh evidence.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--line', type=int, required=True)
    parser.add_argument('--fingerprint', required=True, help='record_sha256 from evidence.json')
    parser.add_argument('--max-chars', type=int, default=4000)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    try:
        print(json.dumps(retrieve(args.session.expanduser(), args.line, args.fingerprint,
                                 args.max_chars, args.offset)))
        return 0
    except (OSError, ValueError) as exc:
        print(f'token-audit retrieve: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
