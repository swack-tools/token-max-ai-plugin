"""Stream local JSONL. Export metadata and sizes, never transcript contents."""
from collections import Counter
import json
from pathlib import Path
import re

from .measure import digest
from .usage import UsageTracker
from .diagnostics import output_text, signals


def session_metadata(path):
    try:
        with path.open(encoding='utf-8') as stream:
            for _ in range(20):
                line = stream.readline()
                if not line:
                    break
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get('type') == 'session_meta':
                    payload = row.get('payload')
                    return payload if isinstance(payload, dict) else {}
    except (OSError, UnicodeError):
        pass
    return {}


def select_session(log_root, project):
    """Latest modified matching cwd; never fall back to an unrelated project."""
    candidates = []
    project = project.resolve()
    for path in log_root.glob('**/*.jsonl'):
        cwd = session_metadata(path).get('cwd')
        if isinstance(cwd, str) and Path(cwd).is_absolute():
            location = Path(cwd).resolve()
            if location == project or project in location.parents:
                try:
                    candidates.append((path.stat().st_mtime_ns, str(path), path))
                except OSError:
                    continue
    return max(candidates)[2] if candidates else None


class ToolEvidence:
    def __init__(self, meter):
        self.meter = meter
        self.calls = {}
        self.groups = {}
        self.outputs = []
        self.messages = []
        self.output_hashes = Counter()
        self.diagnostics = []

    def consume(self, payload, line):
        kind = payload.get('type')
        if kind in ('function_call', 'custom_tool_call'):
            raw_name = payload.get('name', 'unknown')
            name = raw_name if isinstance(raw_name, str) and re.fullmatch(r'[\w.:-]{1,120}', raw_name) else 'unknown'
            raw = payload.get('arguments', payload.get('input', ''))
            arguments = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
            key = digest(name + '\n' + arguments)
            self.calls[str(payload.get('call_id'))] = name
            group = self.groups.setdefault(key, {'tool': name, 'fingerprint': key,
                                                'count': 0, 'lines': []})
            group['count'] += 1
            if len(group['lines']) < 10:
                group['lines'].append(line)
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            content = output_text(payload.get('output'))
            key = digest(content)
            self.output_hashes[key] += 1
            row = {'line': line, 'tool': self.calls.get(str(payload.get('call_id')), 'unknown'),
                   'sha256': key, 'record_sha256': digest(json.dumps(payload, sort_keys=True)),
                   **signals(payload.get('output'), content), **self.meter.measure(content)}
            self.outputs.append(row)
            if row['signals']:
                self.diagnostics.append(row)
        elif kind == 'message':
            role = payload.get('role')
            if role not in ('system', 'developer', 'user', 'assistant', 'tool'):
                role = 'unknown'
            content = output_text(payload.get('content'))
            self.messages.append({'line': line, 'role': role, **self.meter.measure(content)})

    def result(self):
        for row in self.outputs:
            row['identical_output_count'] = self.output_hashes[row['sha256']]
        return {'tool_call_count': sum(g['count'] for g in self.groups.values()),
                'tool_output_bytes': sum(row['bytes'] for row in self.outputs),
                'tool_output_count': len(self.outputs),
                'diagnostics': self.diagnostics,
                'diagnostic_count': len(self.diagnostics),
                'tool_outputs': sorted(self.outputs, key=lambda row: row['bytes'], reverse=True)[:15],
                'repeated_calls': sorted((g for g in self.groups.values() if g['count'] > 1),
                                          key=lambda g: g['count'], reverse=True)[:10],
                'largest_messages': sorted(self.messages, key=lambda row: row['bytes'], reverse=True)[:10]}


def analyze_session(path, meter, usage_only=False):
    tracker, evidence = UsageTracker(), ToolEvidence(meter)
    warnings, malformed, compactions, rows = [], 0, 0, 0
    models = set()
    metadata = session_metadata(path)
    if metadata.get('forked_from_id'):
        warnings.append('Forked session: inherited history/counters may overlap the parent; do not sum across forks.')
    with path.open(encoding='utf-8', errors='replace') as stream:
        for rows, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(row, dict) or not isinstance(row.get('payload'), dict):
                continue
            kind, payload = row.get('type'), row['payload']
            tracker.consume(kind, payload, rows)
            if kind == 'response_item' and not usage_only:
                evidence.consume(payload, rows)
            if kind == 'compacted' or (kind == 'event_msg' and payload.get('type') == 'context_compacted'):
                compactions += 1
            if kind == 'turn_context' and isinstance(payload.get('model'), str):
                models.add(payload['model'])
    measured = tracker.result()
    if malformed:
        warnings.append(f'{malformed} malformed/truncated JSONL lines skipped; log may still be growing.')
    if measured['usage'] is None:
        warnings.append('No valid cumulative usage counters found; usage is unknown.')
    return {'path': str(path), 'cwd': metadata.get('cwd'), 'models': sorted(models),
            'log_lines': rows, 'malformed_lines': malformed, 'compactions': compactions,
            **measured, **evidence.result(), 'warnings': warnings + tracker.warnings,
            'limits': ['Latest cumulative counters are a snapshot, not invoice or subscription quota.',
                       'Text sizes measure logged text, not exact model-visible framing or replay frequency.',
                       'Failure markers are heuristic; detected exit codes and diagnostic references are retained, not bodies. Absence is not success.',
                       'Only leading output/message/call candidates are retained; retrieve omitted evidence from the local log.',
                       'Repeated calls may be intentional; nested calls inside orchestrators are not decomposed.',
                       'Usage intervals locate activity, not causal attribution to a file or tool.']}
