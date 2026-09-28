"""Handle cumulative Codex usage without adding overlapping counters."""
FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens',
          'reasoning_output_tokens', 'total_tokens')


def clean_usage(value):
    if not isinstance(value, dict):
        return None
    if any(type(value.get(k)) is not int or value[k] < 0 for k in FIELDS):
        return None
    result = {k: value[k] for k in FIELDS}
    write = value.get('cache_write_input_tokens')
    if type(write) is int and write >= 0:
        result['cache_write_input_tokens'] = write
    return result


class UsageTracker:
    def __init__(self):
        self.latest = None
        self.latest_line = None
        self.source = None
        self.duplicates = 0
        self.records = {}
        self.warnings = []
        self.increments = []

    def consume(self, kind, payload, line):
        value = None
        if kind == 'token_usage_record':
            record = clean_usage(payload.get('usage'))
            response_id = payload.get('response_id')
            if record and isinstance(response_id, str):
                if response_id in self.records and self.records[response_id] != record:
                    self.warnings.append('Conflicting usage for a repeated response ID.')
                self.records[response_id] = record
            value = payload.get('thread_token_usage')
        elif kind == 'event_msg' and payload.get('type') == 'token_count':
            info = payload.get('info')
            if isinstance(info, dict):
                value = info.get('total_token_usage')
        if value is None:
            return
        current = clean_usage(value)
        if current is None:
            self.warnings.append(f'Invalid usage counters at log line {line}; skipped.')
            return
        if self.latest == current:
            self.duplicates += 1
            return
        if self.latest:
            if any(current[k] < self.latest[k] for k in FIELDS):
                self.warnings.append(f'Counter reset/decrease at line {line}; latest segment only, not lifetime usage.')
            else:
                self.increments.append({'line': line, 'after_line': self.latest_line,
                    **{k: current[k] - self.latest[k] for k in FIELDS}})
        self.latest, self.latest_line, self.source = current, line, kind

    def result(self):
        value = dict(self.latest) if self.latest else None
        if value is not None:
            difference = value['input_tokens'] - value['cached_input_tokens']
            value['uncached_input_tokens'] = difference if difference >= 0 else None
            if difference < 0 or value['reasoning_output_tokens'] > value['output_tokens']:
                self.warnings.append('Inconsistent provider subset counters; do not use derived savings.')
            if value['total_tokens'] != value['input_tokens'] + value['output_tokens']:
                self.warnings.append('Reported total differs from input + output; preserved provider value.')
        return {'usage': value, 'usage_line': self.latest_line, 'usage_source': self.source,
                'duplicate_snapshots': self.duplicates, 'response_records': len(self.records),
                'largest_usage_intervals': sorted(self.increments,
                    key=lambda row: row['total_tokens'], reverse=True)[:10]}
