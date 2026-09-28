#!/usr/bin/env python3
"""Synthetic representation benchmark, not a model-quality or billing evaluation."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/token-audit'
sys.path.insert(0, str(SKILL / 'scripts'))
from auditlib.measure import TextMeter
from auditlib.project import analyze_project
from auditlib.report import render
from auditlib.session import analyze_session
from retrieve import retrieve
from query import select


def fixture(count, lines):
    usage = dict(input_tokens=1000, cached_input_tokens=600, output_tokens=200,
                 reasoning_output_tokens=50, total_tokens=1200)
    rows = [dict(type='session_meta', payload=dict(cwd='/fixture'))]
    for n in range(count):
        rows.extend([
            dict(type='response_item', payload=dict(type='function_call',
                 name='exec_command', call_id=str(n), arguments='{"cmd":"cat build.log"}')),
            dict(type='response_item', payload=dict(type='function_call_output',
                 call_id=str(n), output='Build progress: completed routine step successfully.\n' * lines))])
    # A short, task-critical observation must NOT be assumed absent from a size-ranked report.
    rows.append(dict(type='response_item', payload=dict(type='function_call_output',
                call_id='critical', output='ERROR: migration checksum mismatch')))
    snap = dict(type='event_msg', payload=dict(type='token_count',
                info=dict(total_token_usage=usage)))
    rows.extend([snap, snap])
    return ''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows), usage


def run_case(name, count, lines, meter):
    raw, expected = fixture(count, lines)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        (root / 'AGENTS.md').write_text('Run the relevant tests before proposing a change.\n')
        (root / 'main.py').write_text('def add(a, b):\n    return a + b\n')
        # Keep logs outside the project inventory, as normal Codex rollouts are.
        with tempfile.TemporaryDirectory() as logs:
            log = Path(logs) / 'session.jsonl'
            log.write_text(raw)
            session = analyze_session(log, meter)
            critical = next(row for row in session['diagnostics'] if row['line'] == 2 * count + 2)
            recovered = retrieve(log, critical['line'], critical['record_sha256'])
            usage_cli = subprocess.run([sys.executable, str(SKILL / 'scripts/audit.py'),
                '--project', str(root), '--session', str(log), '--usage-only'],
                capture_output=True, text=True, check=True).stdout
        project = analyze_project(root, meter)
    project['root'], session['path'] = '/fixture', '/fixture/session.jsonl'
    report = dict(project=project, session=session, generated_at='synthetic fixture',
                  text_encoding=meter.encoding)
    compact = render(report)
    checks = {
        'critical_error_reference_preserved': critical['line'] == 2 * count + 2,
        'critical_error_recovered_exactly': recovered['text'] == 'ERROR: migration checksum mismatch',
        'provider_counters_preserved': all(session['usage'][k] == v for k, v in expected.items()),
        'cache_subset_subtracted': session['usage']['uncached_input_tokens'] == 400,
        'duplicate_snapshot_not_added': session['duplicate_snapshots'] == 1,
        'tool_output_count_preserved': session['tool_output_count'] == count + 1,
        'largest_output_bytes_correct': session['tool_outputs'][0]['bytes'] == len(
            ('Build progress: completed routine step successfully.\n' * lines).encode()),
        'repeated_call_count_correct': (session['repeated_calls'][0]['count'] == count
                                      if count > 1 else not session['repeated_calls']),
    }
    if not all(checks.values()):
        raise ValueError(f'Fixture evidence fidelity failed: {checks}')
    critical_line = 2 * count + 2
    # This baseline answers only one question. It is intentionally cheaper and narrower.
    targeted = json.dumps(expected, sort_keys=True)
    skill_text = (SKILL / 'SKILL.md').read_text() + '\n' + (SKILL / 'references/collector.md').read_text()
    references = '\n'.join((SKILL / 'references' / p).read_text()
                           for p in ('review.md', 'sources.md'))
    tokens = lambda text: meter.measure(text)['text_tokens']
    raw_tokens, compact_tokens = tokens(raw), tokens(compact)
    return dict(case=name, fixture_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                raw_log_text_tokens=raw_tokens, evidence_markdown_text_tokens=compact_tokens,
                skill_plus_evidence_text_tokens=tokens(skill_text + '\n' + compact),
                skill_references_evidence_text_tokens=tokens(skill_text + '\n' + references + '\n' + compact),
                targeted_usage_only_text_tokens=tokens(targeted),
                usage_only_cli_text_tokens=tokens(usage_cli),
                evidence_plus_retrieval_text_tokens=tokens(compact + '\n' + json.dumps(recovered)),
                evidence_query_retrieval_text_tokens=tokens(compact + '\n' + json.dumps(
                    select(report, 'diagnostics')) + '\n' + json.dumps(recovered)),
                summary_reduction_percent=round(100 * (1 - compact_tokens / raw_tokens), 2),
                metadata_checks=checks,
                critical_error_body_preserved='migration checksum mismatch' in compact,
                critical_error_in_diagnostics=critical['line'] == critical_line,
                critical_error_recovered_exactly=checks['critical_error_recovered_exactly'],
                critical_error_metadata_in_top15=any(r['line'] == critical_line for r in session['tool_outputs']))


def source_fingerprint():
    source_files = sorted([Path(__file__), *SKILL.rglob('*.py'), SKILL / 'SKILL.md',
                           *sorted((SKILL / 'references').glob('*.md'))])
    digest = hashlib.sha256()
    for path in source_files:
        digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def benchmark(encoding='o200k_base'):
    meter = TextMeter(encoding)
    return dict(schema_version=2, measurement='text representation only; no model calls',
                encoding=encoding, tiktoken_version=importlib.metadata.version('tiktoken'),
                source_sha256=source_fingerprint(),
                cases=[run_case(name, count, lines, meter) for name, count, lines in
                       [('tiny', 1, 1), ('verbose', 1, 2000), ('repeated', 8, 400),
                        ('crowded', 20, 100)]],
                limitations=['Synthetic repetitive data; not a production workload distribution.',
                             'Metadata assertions are not model task-quality evaluations.',
                             'Bodies are omitted; heuristic diagnostic references survive size ranking and support bounded retrieval.',
                             'No framing, history replay, audit reasoning, retries or validation costs measured.',
                             'Reference loading may be conditional; both overhead scenarios are reported.',
                             'Targeted usage projection answers a narrower question than the full audit.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encoding', default='o200k_base')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(benchmark(args.encoding), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
