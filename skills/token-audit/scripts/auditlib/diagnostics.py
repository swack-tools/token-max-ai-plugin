"""Conservative failure candidates, kept independently of output size rankings."""
import json
import re

PATTERNS = {
    'error_marker': re.compile(r'\b(?:error|fatal|panic|traceback|exception)\b', re.I),
    'failure_marker': re.compile(r'\b(?:failed|failure|failing)\b', re.I),
    'truncation_marker': re.compile(r'\b(?:truncated|output limit|token limit)\b', re.I),
}


def decode_output(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    return value


def output_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(output_text(item) for item in value)
    if isinstance(value, dict):
        if value.get('type') in ('input_text', 'output_text', 'text'):
            return value.get('text') if isinstance(value.get('text'), str) else ''
        # Only known tool text containers; never serialize arbitrary fields/images.
        for key in ('output', 'content'):
            if key in value:
                return output_text(value[key])
    return ''


def signals(value, text):
    obj = decode_output(value)
    codes = set()
    flags = {name for name, pattern in PATTERNS.items() if pattern.search(text)}
    if isinstance(obj, dict):
        for container in (obj, obj.get('metadata')):
            if not isinstance(container, dict):
                continue
            code = container.get('exit_code')
            if type(code) is int:
                codes.add(code)
            if container.get('isError') is True:
                flags.add('tool_error')
    # Codex's textual shell wrapper. An anchored label is still evidence, not trusted truth.
    codes.update(int(code) for code in re.findall(
        r'(?im)^(?:Process exited with code|Exit code:)\s*(-?\d+)\s*$', text))
    if any(codes):
        flags.add('nonzero_exit')
    return {'signals': sorted(flags), 'exit_codes': sorted(codes)}
