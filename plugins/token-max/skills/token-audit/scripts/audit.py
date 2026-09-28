#!/usr/bin/env python3
"""Collect local Codex usage and project evidence without sending data anywhere."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from auditlib.measure import TextMeter
from auditlib.project import analyze_project
from auditlib.report import render
from auditlib.session import analyze_session, select_session, session_metadata


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--session', default='auto', help='auto, latest, none, or a Codex JSONL path')
    parser.add_argument('--log-root', type=Path,
                        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions')
    parser.add_argument('--out', type=Path, help='Default: PROJECT/.token-audit')
    parser.add_argument('--encoding', help='Optional tiktoken encoding, e.g. o200k_base; never auto-guessed')
    parser.add_argument('--instruction', type=Path, action='append', default=[],
                        help='Additional instruction file to measure, repeatable')
    parser.add_argument('--max-file-bytes', type=int, default=1_000_000)
    parser.add_argument('--usage-only', action='store_true',
                        help='Print usage and warnings only; do not scan project files or write reports')
    parser.add_argument('--full-report', action='store_true', help='Write expanded Markdown instead of compact default')
    return parser.parse_args()


def choose_session(args):
    if args.session == 'none':
        return None
    if args.session not in ('auto', 'latest'):
        return Path(args.session).expanduser().resolve(strict=True)
    thread_id = os.environ.get('CODEX_THREAD_ID', '')
    if args.session == 'auto' and thread_id and all(c in '0123456789abcdef-' for c in thread_id):
        matches = list(args.log_root.glob(f'**/*{thread_id}.jsonl'))
        for path in matches:
            cwd = session_metadata(path).get('cwd')
            if isinstance(cwd, str) and Path(cwd).is_absolute():
                cwd = Path(cwd).resolve()
                if cwd == args.project or args.project in cwd.parents:
                    return path
    return select_session(args.log_root, args.project)


def save_report(out, report):
    destinations = {out / 'evidence.json': json.dumps(report, indent=2) + '\n',
                    out / 'evidence.md': render(report)}
    if out.is_symlink() or any(path.is_symlink() for path in destinations):
        raise ValueError('Refusing to overwrite a symlinked evidence path.')
    out.mkdir(parents=True, exist_ok=True)
    for path, text in destinations.items():
        # Atomic replacement never follows a destination file symlink.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=out, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(text)
                stream.flush()
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)


def main():
    args = parse_args()
    try:
        args.project = args.project.expanduser().resolve(strict=True)
        if not args.project.is_dir() or args.max_file_bytes <= 0:
            raise ValueError('Provide a project directory and a positive file byte limit.')
        args.log_root = args.log_root.expanduser().resolve()
        meter = TextMeter(args.encoding)
        session_path = choose_session(args)
        if args.usage_only:
            session = analyze_session(session_path, meter, usage_only=True) if session_path else None
            print(json.dumps({'usage': session['usage'] if session else None,
                'usage_line': session['usage_line'] if session else None,
                'warnings': session['warnings'] if session else ['No matching session.'],
                'scope': 'last cumulative snapshot; not invoice or task savings'}))
            return 0
        out = (args.out or args.project / '.token-audit').expanduser().absolute()
        generated_files = [out / name for name in ('evidence.md', 'evidence.json', 'AUDIT.md')]
        report = {'schema_version': 2, 'generated_at': datetime.now(timezone.utc).isoformat(),
                  'full_report': args.full_report,
                  'text_encoding': meter.encoding,
                  'project': analyze_project(args.project, meter, args.instruction, args.max_file_bytes,
                                             excluded_paths=generated_files),
                  'session': analyze_session(session_path, meter) if session_path else None}
        save_report(out, report)
        usage = report['session']['usage'] if report['session'] else None
        print(json.dumps({'evidence': str(out / 'evidence.md'), 'json': str(out / 'evidence.json'),
                          'files_scanned': report['project']['files_scanned'], 'usage': usage}))
        return 0
    except (OSError, ValueError) as exc:
        print(f'token-audit: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
